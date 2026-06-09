import os
import re
import json
import asyncio
import difflib
from dotenv import load_dotenv
load_dotenv()
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional

from google.antigravity import Agent, LocalAgentConfig
from engine.utils.markdown import load_settings, parse_markdown
from engine.utils.llm_fallback import call_llm_with_fallback
from engine.tools.vault_tools import (
    get_vault_path,
    list_unprocessed_raw,
    read_raw_file,
    write_wiki_page,
    save_processed_file,
    append_to_log,
    update_index,
    search_wiki
)
from engine.git_ops import auto_commit

# Pydantic schemas for Structured Outputs / Validation
class SourceSummary(BaseModel):
    title: str = Field(description="Titolo identificativo della sorgente")
    summary: str = Field(description="Riassunto strutturato e denso del contenuto")
    key_points: List[str] = Field(description="Elenco dei punti chiave della sorgente")
    tags: List[str] = Field(description="Lista di tag associati")

class ConceptExtraction(BaseModel):
    name: str = Field(description="Nome del concetto (es. Transfer Learning)")
    description: str = Field(description="Spiegazione approfondita del concetto emerso nel testo")
    related: List[str] = Field(default_factory=list, description="Lista di wikilink a concetti correlati, es. ['[[Deep Learning]]']")

    @field_validator('related', mode='before')
    @classmethod
    def flatten_related(cls, v):
        if isinstance(v, list):
            flat = []
            for item in v:
                if isinstance(item, list):
                    for subitem in item:
                        if isinstance(subitem, str):
                            flat.append(subitem)
                        else:
                            flat.append(str(subitem))
                elif isinstance(item, str):
                    flat.append(item)
                else:
                    flat.append(str(item))
            return flat
        return v

class EntityExtraction(BaseModel):
    name: str = Field(description="Nome dell'entità rilevata nel testo (persona, organizzazione, progetto, evento, appuntamento, microtema)")
    description: str = Field(description="Breve descrizione o biografia dell'entità nel contesto del testo")
    is_existing: bool = Field(description="True se questa entità corrisponde a una delle entità suggerite del vault")
    canonical_name: Optional[str] = Field(None, description="Nome esatto (canonical) dell'entità suggerita se is_existing è True, altrimenti null")
    entity_type: str = Field("entity", description="Tipo specifico di entità: 'person', 'organization', 'project', 'event', 'appointment', 'microtheme', o 'entity' generico")

class WikiIngestResponse(BaseModel):
    is_noise: bool = Field(description="True se il testo grezzo è rumore, spam, transazioni bancarie generiche non associate a persone, o notifiche esterne irrilevanti")
    source_summary: Optional[SourceSummary] = None
    concepts: List[ConceptExtraction] = Field(default_factory=list)
    entities: List[EntityExtraction] = Field(default_factory=list)

def get_agent_instructions(agent_name: str) -> str:
    vault_path = get_vault_path()
    agents_md = os.path.join(vault_path, "agents.md")
    if not os.path.exists(agents_md):
        return ""
    with open(agents_md, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = rf"##\s+{agent_name}\s*\n(.*?)(?=\n##(?![#])|$)"
    match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""

def load_aliases_map(vault_path: str) -> dict:
    aliases_map = {}
    
    # Directories to scan
    scan_dirs = [
        ("entities", os.path.join(vault_path, "wiki", "entities")),
        ("crm", os.path.join(vault_path, "CRM"))
    ]
    
    for folder_type, search_dir in scan_dirs:
        if not os.path.exists(search_dir):
            continue
        for root, _, files in os.walk(search_dir):
            for file in files:
                if file.endswith(".md") and not file.startswith("."):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, vault_path)
                    canonical_name = os.path.splitext(file)[0]
                    
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        fm, _ = parse_markdown(content)
                    except Exception:
                        fm = {}
                        
                    # Resolve clean canonical name from YAML name field if present
                    canonical_name_clean = fm.get("name", canonical_name).strip()
                    
                    entry = {
                        "canonical": canonical_name_clean,
                        "path": rel_path,
                        "type": folder_type
                    }
                    
                    # Map canonical names (case-insensitive)
                    aliases_map[canonical_name_clean.lower()] = entry
                    aliases_map[canonical_name.lower()] = entry
                    
                    # Map aliases if present in YAML
                    aliases = fm.get("aliases", [])
                    if isinstance(aliases, list):
                        for alias in aliases:
                            if isinstance(alias, str) and alias.strip():
                                aliases_map[alias.lower().strip()] = entry
                    elif isinstance(aliases, str) and aliases.strip():
                        aliases_map[aliases.lower().strip()] = entry
                        
    return aliases_map

def extract_candidate_entities(content: str, aliases_map: dict) -> list[dict]:
    if not content:
        return []
        
    # Regex to find words with capital letters or acronyms
    pattern = r'\b[A-Z][a-zA-Z0-9àèìòù’\'-]*(?:\s+[A-Z][a-zA-Z0-9àèìòù’\'-]*)*\b|\b[A-Z]{3,}\b'
    candidates = set()
    for match in re.finditer(pattern, content):
        cand = match.group(0).strip()
        if len(cand) >= 3:
            candidates.add(cand)
            
    suggested = {}
    alias_keys = list(aliases_map.keys())
    
    for cand in candidates:
        cand_lower = cand.lower()
        if cand_lower in aliases_map:
            entry = aliases_map[cand_lower]
            suggested[entry["canonical"]] = entry
        else:
            # Fuzzy match close name variations (high cutoff to avoid wrong matches)
            matches = difflib.get_close_matches(cand_lower, alias_keys, n=1, cutoff=0.85)
            if matches:
                entry = aliases_map[matches[0]]
                suggested[entry["canonical"]] = entry
                
    return list(suggested.values())

def find_existing_page(vault_path: str, folder_type: str, clean_name: str) -> str or None:
    search_dir = os.path.join(vault_path, "wiki", folder_type)
    if not os.path.exists(search_dir):
        return None
    filename_to_find = f"{clean_name}.md".lower()
    for root, _, files in os.walk(search_dir):
        for file in files:
            if file.lower() == filename_to_find:
                return os.path.relpath(os.path.join(root, file), vault_path)
    return None

def resolve_category_folder(vault_path: str, base_type: str, category: str) -> str:
    """
    Risolve il percorso della cartella della categoria in base alle cartelle esistenti nel vault.
    Supporta anche un mapping esplicito tramite la variabile d'ambiente CATEGORY_MAPPINGS.
    """
    # 1. Verifica se c'è un mapping esplicito in CATEGORY_MAPPINGS
    mappings_str = os.getenv("CATEGORY_MAPPINGS")
    if mappings_str:
        try:
            mapping = json.loads(mappings_str)
            if category in mapping:
                return mapping[category]
        except Exception:
            pass

    target_dir = os.path.join(vault_path, "wiki", base_type)
    if not os.path.exists(target_dir):
        return category
        
    # Se la cartella esatta esiste già, usala direttamente
    if os.path.isdir(os.path.join(target_dir, category)):
        return category
        
    # Scansiona le sottocartelle esistenti
    existing_subdirs = []
    try:
        for root, dirs, _ in os.walk(target_dir):
            for d in dirs:
                if d.startswith('.'):
                    continue
                full_path = os.path.join(root, d)
                rel_path = os.path.relpath(full_path, target_dir)
                existing_subdirs.append(rel_path)
    except Exception:
        return category
        
    if not existing_subdirs:
        return category
        
    # Prova corrispondenza esatta sull'ultimo segmento (case-insensitive)
    category_parts = [p.lower() for p in category.split('/') if p]
    if not category_parts:
        return category
        
    last_part = category_parts[-1]
    for subdir in existing_subdirs:
        subdir_parts = [p.lower() for p in subdir.split('/') if p]
        if subdir_parts and subdir_parts[-1] == last_part:
            return subdir
            
    # Prova corrispondenza fuzzy basata su parole sovrapposte
    def get_words(path: str) -> set:
        normalized = re.sub(r'[^a-zA-Z0-9]', ' ', path).lower()
        return {w for w in normalized.split() if len(w) > 2}
        
    category_words = get_words(category)
    if not category_words:
        return category
        
    best_match = None
    best_score = 0
    for subdir in existing_subdirs:
        subdir_words = get_words(subdir)
        overlap = category_words.intersection(subdir_words)
        score = len(overlap)
        if score > best_score:
            best_score = score
            best_match = subdir
            
    if best_match and best_score > 0:
        return best_match
        
    return category

def get_category_folder(title: str, body: str = "") -> str:
    text = (title + " " + body).lower()
    categories = {
        'Sindacati/USB': ['usb', 'pubblico impiego', 'sanità', 'vigili del fuoco', 'vvff', 'ministero interno', 'ministero dell\'istruzione', 'rsu', 'sciopero generale', 'sindacato conflittuale'],
        'Sindacati/SPI_CGIL': ['spi', 'cgil', 'pensionati', 'non autosufficienza', 'cgil milano', 'pensionati.it', 'pensionati.milano.it'],
        'Associazioni/Arci': ['arci', 'maschilisti anonimi', 'arcibo', 'bologna', 'tesseramento arci', 'slogan arci'],
        'Associazioni/Auser': ['auser', 'auser lazio'],
        'Cultura/Scabec': ['scabec', 'artecard', 'campania artecard', 'pass turistico', 'soprintendenza', 'museale'],
        'Istituzioni/Puglia': ['regione puglia', 'innovapuglia', 'bari', 'comune di bari', 'spazio13', 'sp13', 'artisti digitali', 'co-progettazione giovanile', 'foggia', 'ruvo', 'tuturano', 'puglia creativa'],
        'Didattica/Scuola_Aperta': ['scuola', 'didattica', 'laboratori brevi', 'mosaic', 'decennale', 'piattaforma', 'culture swing'],
        'AI_LLM_Coding': ['ai', 'llm', 'ollama', 'gemini', 'openai', 'n8n', 'retool', 'gitlab', 'cicd', 'coding', 'software', 'modelli', 'inferenza', 'rag', 'recompil', 'python', 'git_ops', 'hosting', 'ftp', 'server', 'smtp', 'developer'],
        'Design_Branding': ['design', 'branding', 'type design', 'font', 'visual', 'grafica', 'fizma', 'figma', 'tipograf', 'glifi', 'lettering', 'carattere tipografico', 'manifesto', 'locandina', 'advising', 'impaginazione', 'logo', 'logotipo', 'copertina', 'souvenir']
    }
    for category, keywords in categories.items():
        if any(k in text for k in keywords):
            return category
    return "General"

async def ingest_file(config: LocalAgentConfig, rel_path: str, existing_concepts: list, aliases_map: dict) -> bool:
    print(f"Elaborazione file: {rel_path}...")
    try:
        content = read_raw_file(rel_path)
    except Exception as e:
        print(f"Errore lettura {rel_path}: {e}")
        return False
        
    vault_path = get_vault_path()
    
    # 1. LIVELLO 1: Pre-filtro statico per le email (basato su settings.md)
    if rel_path.startswith("raw/mail/"):
        settings = load_settings(vault_path)
        mail_settings = settings.get("sources", {}).get("apple_mail", {})
        try:
            fm, _ = parse_markdown(content)
            sender = fm.get("sender", "").lower()
            subject = fm.get("subject", "").lower()
            
            # Esclusione per mittente specifico
            exclude_senders = mail_settings.get("exclude_senders", [])
            for x in exclude_senders:
                if x.strip() and x.lower() in sender:
                    print(f"  - Pre-filtro: Saltato '{rel_path}' (mittente '{sender}' escluso da '{x}')")
                    save_processed_file(rel_path)
                    append_to_log(f"[AI Ingest - Pre-filtro] Saltato '{rel_path}' (mittente escluso: '{x}')")
                    return True
                    
            # Esclusione per dominio del mittente
            exclude_domains = mail_settings.get("exclude_domains", [])
            for x in exclude_domains:
                if x.strip() and x.lower() in sender:
                    print(f"  - Pre-filtro: Saltato '{rel_path}' (dominio '{sender}' escluso da '{x}')")
                    save_processed_file(rel_path)
                    append_to_log(f"[AI Ingest - Pre-filtro] Saltato '{rel_path}' (dominio escluso: '{x}')")
                    return True
                    
            # Esclusione per parole chiave nell'oggetto
            exclude_subjects = mail_settings.get("exclude_subjects", [])
            for x in exclude_subjects:
                if x.strip() and x.lower() in subject:
                    print(f"  - Pre-filtro: Saltato '{rel_path}' (oggetto contiene '{x}')")
                    save_processed_file(rel_path)
                    append_to_log(f"[AI Ingest - Pre-filtro] Saltato '{rel_path}' (oggetto contiene parole chiave escluse: '{x}')")
                    return True
        except Exception as e:
            print(f"Avviso: errore durante l'applicazione del pre-filtro statico per {rel_path}: {e}")
            
    # Local Entity Resolution: extract candidate entities for limited context
    suggested_entities = extract_candidate_entities(content, aliases_map)
    suggested_names_paths = [f"- {e['canonical']} (percorso: [[{e['path']}]])" for e in suggested_entities]
    suggested_entities_str = "\n".join(suggested_names_paths) if suggested_names_paths else "Nessuna entità corrispondente trovata nel vault."

    prompt = f"""
Hai il compito di elaborare la seguente sorgente grezza e integrarla nella wiki.
Percorso file: {rel_path}
Contenuto del file:
---
{content}
---

Pagine esistenti nel wiki per contestualizzare i link:
Concetti esistenti: {existing_concepts}

Entità esistenti nel Secondo Cervello che potrebbero corrispondere (suggerite tramite fuzzy matching):
{suggested_entities_str}

Disambiguazione entità (IMPORTANTE):
Per ogni persona, organizzazione o progetto (entità) rilevato nel testo, controlla se corrisponde a una delle entità esistenti suggerite sopra.
- Se corrisponde (anche se scritta con lievi differenze o alias), imposta "is_existing" a true e "canonical_name" al suo nome esatto suggerito.
- Se non corrisponde a nessuna entità esistente suggerita, imposta "is_existing" a false e "canonical_name" a null.

Genera un output JSON strutturato che rispecchi esattamente questo schema Pydantic:
```json
{{
  "is_noise": false, // imposta a true se il testo è rumore o spam irrilevante
  "source_summary": {{
    "title": "Titolo identificativo della sorgente",
    "summary": "Riassunto strutturato e denso del contenuto",
    "key_points": ["Punto chiave 1", "Punto chiave 2"],
    "tags": ["tag1", "tag2"]
  }},
  "concepts": [
    {{
      "name": "Nome del Concetto (es. Transfer Learning)",
      "description": "Spiegazione approfondita del concetto emerso",
      "related": ["[[Nome Altro Concetto Correlato]]"]
    }}
  ],
  "entities": [
    {{
      "name": "Nome dell'Entità (es. Andrej Karpathy)",
      "description": "Descrizione del ruolo dell'entità nel testo",
      "is_existing": true, // o false
      "canonical_name": "Nome Esatto Canonico" // o null
    }}
  ]
}}
```
Restituisci solo ed esclusivamente il blocco JSON.
"""
    
    system_instructions = config.system_instructions
    try:
        resp_text = await call_llm_with_fallback(prompt, system_instructions, config)
    except Exception as e:
        print(f"Errore critico durante l'elaborazione del file {rel_path} con tutti i provider: {e}")
        return False
        
    try:
        # Extract JSON from markdown code block
        json_match = re.search(r"```json\s*(.*?)\s*```", resp_text, re.DOTALL)
        json_str = json_match.group(1) if json_match else resp_text.strip()
        
        # Pydantic validation
        response_data = WikiIngestResponse.model_validate_json(json_str)
        data = response_data.model_dump()
    except Exception as e:
        print(f"Errore durante l'estrazione LLM o parsing JSON/Pydantic per {rel_path}: {e}")
        if 'resp_text' in locals():
            print(f"Risposta ricevuta dal modello:\n{resp_text}")
        return False
        
    # 2. LIVELLO 2: Post-filtro semantico per lo spam e il rumore
    if data.get("is_noise", False):
        print(f"  - Post-filtro: Saltato '{rel_path}' (identificato come rumore/spam dall'LLM)")
        save_processed_file(rel_path)
        append_to_log(f"[AI Ingest - Post-filtro] Saltato '{rel_path}' (identificato come rumore/spam)")
        return True
        
    # Write files
    # 1. Source page
    source_summary = data.get("source_summary", {}) or {}
    source_title = source_summary.get("title", os.path.basename(rel_path).replace(".md", ""))
    clean_title = re.sub(r'[\\/*?:"<>|]', "", source_title)
    
    source_path = find_existing_page(vault_path, "sources", clean_title)
    if not source_path:
        category = get_category_folder(source_title, source_summary.get("summary", ""))
        category = resolve_category_folder(vault_path, "sources", category)
        source_path = f"wiki/sources/{category}/{clean_title}.md"
    
    source_body = f"# {source_title}\n\n{source_summary.get('summary', '')}\n\n## Punti Chiave\n"
    for pt in source_summary.get("key_points", []):
        source_body += f"- {pt}\n"
    source_body += f"\n---\n**Fonte Originale**: {rel_path}\n"
    
    source_fm = {
        "type": "source",
        "tags": source_summary.get("tags", []),
        "original_file": rel_path
    }
    
    write_wiki_page(source_path, source_body, source_fm)
    update_index(source_path, source_summary.get("summary", "")[:100])
    
    # 2. Concept pages
    for concept in data.get("concepts", []):
        c_name = concept.get("name")
        if not c_name:
            continue
        c_clean = re.sub(r'[\\/*?:"<>|]', "", c_name)
        
        c_path = find_existing_page(vault_path, "concepts", c_clean)
        if not c_path:
            category = get_category_folder(c_name, concept.get("description", ""))
            category = resolve_category_folder(vault_path, "concepts", category)
            c_path = f"wiki/concepts/{category}/{c_clean}.md"
        
        c_body = ""
        c_fm = {"type": "concept", "related": concept.get("related", [])}
        if os.path.exists(os.path.join(vault_path, c_path)):
            try:
                with open(os.path.join(vault_path, c_path), "r", encoding="utf-8") as f:
                    c_old_fm, c_old_body = parse_markdown(f.read())
                    c_body = c_old_body + "\n\n"
                    c_fm = c_old_fm
                    old_rel = c_old_fm.get("related", [])
                    c_fm["related"] = list(set(old_rel + concept.get("related", [])))
            except Exception:
                pass
                
        c_body += f"### Aggiornamento da [[{clean_title}]]\n{concept.get('description', '')}\n"
        
        write_wiki_page(c_path, c_body, c_fm)
        update_index(c_path, concept.get("description", "")[:100])
        
    # 3. Entity pages
    for entity in data.get("entities", []):
        e_name = entity.get("name")
        if not e_name:
            continue
        
        is_existing = entity.get("is_existing", False)
        canonical_name = entity.get("canonical_name")
        
        # Use canonical name if mapped, else extracted name
        target_name = canonical_name if (is_existing and canonical_name) else e_name
        e_clean = re.sub(r'[\\/*?:"<>|]', "", target_name)
        
        e_path = None
        if is_existing and canonical_name:
            # Check pre-loaded aliases_map
            matched_entry = aliases_map.get(canonical_name.lower())
            if matched_entry:
                e_path = matched_entry["path"]
                
        if not e_path:
            e_path = find_existing_page(vault_path, "entities", e_clean)
            
        if not e_path:
            category = get_category_folder(target_name, entity.get("description", ""))
            category = resolve_category_folder(vault_path, "entities", category)
            e_path = f"wiki/entities/{category}/{e_clean}.md"
        
        e_body = ""
        e_type = entity.get("entity_type", "entity")
        if e_type not in ["person", "organization", "project", "event", "appointment", "microtheme", "entity"]:
            e_type = "entity"
        e_fm = {"type": e_type}
        if os.path.exists(os.path.join(vault_path, e_path)):
            try:
                with open(os.path.join(vault_path, e_path), "r", encoding="utf-8") as f:
                    e_old_fm, e_old_body = parse_markdown(f.read())
                    e_body = e_old_body + "\n\n"
                    # Preserve all existing metadata fields (aliases, phone, email, etc.)
                    e_fm = e_old_fm
                    if "type" not in e_fm or e_fm["type"] == "entity":
                        e_fm["type"] = e_type
            except Exception:
                pass
                
        e_body += f"### Aggiornamento da [[{clean_title}]]\n{entity.get('description', '')}\n"
        
        write_wiki_page(e_path, e_body, e_fm)
        update_index(e_path, entity.get("description", "")[:100])
        
    save_processed_file(rel_path)
    append_to_log(f"[AI Ingest] Elaborato '{rel_path}' -> Creato source [[{clean_title}]]")
    print(f"Completata elaborazione per: {rel_path}")
    return True

async def run_ingest(dry_run: bool = False, source_filter: str = None):
    vault_path = get_vault_path()
    unprocessed = list_unprocessed_raw()
    
    if source_filter:
        if source_filter == "mail":
            unprocessed = [u for u in unprocessed if u.startswith("raw/mail/")]
        else:
            unprocessed = [u for u in unprocessed if source_filter in u]
        
    if not unprocessed:
        if source_filter:
            print(f"Nessun nuovo file da elaborare in raw/ o Meetings/ corrispondente al filtro '{source_filter}'.")
        else:
            print("Nessun nuovo file da elaborare in raw/ o Meetings/.")
        return
        
    if dry_run:
        print(f"[Dry-run] Trovati {len(unprocessed)} file non elaborati:")
        for u in unprocessed:
            print(f"- {u}")
        return
        
    # Walk existing concepts once to cache them
    existing_concepts = []
    concepts_dir = os.path.join(vault_path, "wiki", "concepts")
    if os.path.exists(concepts_dir):
        for root, _, files in os.walk(concepts_dir):
            for file in files:
                if file.endswith(".md") and not file.startswith("."):
                    existing_concepts.append(file.replace(".md", ""))
                    
    # Walk existing entities and CRM once to index aliases
    print("Costruzione indice degli alias delle entità...")
    aliases_map = load_aliases_map(vault_path)
    print(f"Indice alias caricato con successo ({len(aliases_map)} chiavi).")
        
    # Setup Agent
    settings = load_settings(vault_path)
    model = settings.get("models", {}).get("ingest_agent", "gemini-3.5-flash")
    instructions = get_agent_instructions("Ingest Agent")
    
    auth = settings.get("google_auth", {})
    kwargs = {}
    if auth.get("use_vertex", False):
        kwargs["vertex"] = True
        if auth.get("project_id"):
            kwargs["project"] = auth["project_id"]
        if auth.get("location"):
            kwargs["location"] = auth["location"]
            
    config = LocalAgentConfig(
        model=model,
        system_instructions=instructions,
        **kwargs
    )
    
    print(f"Avvio Ingest Agent con modello '{model}'...")
    processed_count = 0
    batch_size = 10
    for rel_path in unprocessed:
        success = await ingest_file(config, rel_path, existing_concepts, aliases_map)
        if success:
            processed_count += 1
            if processed_count % batch_size == 0:
                print(f"Salvataggio progresso: commit incrementale di {processed_count} file elaborati...")
                auto_commit(vault_path, f"[AI Ingest] Elaborazione parziale: {processed_count} file sorgente")
        await asyncio.sleep(2)
            
    if processed_count > 0:
        if processed_count % batch_size != 0:
            auto_commit(vault_path, f"[AI Ingest] Completata elaborazione: {processed_count} nuovi file sorgente")
            
if __name__ == "__main__":
    import sys
    src_filter = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run_ingest(source_filter=src_filter))

