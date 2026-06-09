import os
import re
import json
import asyncio
import datetime
import difflib
from pydantic import BaseModel, Field
from typing import List
from google.antigravity import LocalAgentConfig
from engine.utils.markdown import load_settings, parse_markdown, to_markdown
from engine.utils.llm_fallback import call_llm_with_fallback
from engine.tools.vault_tools import (
    get_vault_path,
    append_to_log
)
from engine.git_ops import auto_commit

# Modelli Pydantic per la validazione strutturata delle proposte
class MergeProposal(BaseModel):
    id: str = Field(description="ID della proposta di fusione, es: M1, M2")
    source: str = Field(description="Percorso relativo del nodo da fondere (sorgente)")
    target: str = Field(description="Percorso relativo del nodo destinatario (destinazione)")
    reason: str = Field(description="Motivazione dettagliata in italiano")

class HierarchyProposal(BaseModel):
    id: str = Field(description="ID della proposta gerarchica, es: H1, H2")
    parent: str = Field(description="Percorso relativo del parent")
    child: str = Field(description="Percorso relativo del child")
    reason: str = Field(description="Motivazione dettagliata in italiano")

class LinkProposal(BaseModel):
    id: str = Field(description="ID della proposta di collegamento, es: L1, L2")
    source: str = Field(description="Percorso relativo del nodo A")
    target: str = Field(description="Percorso relativo del nodo B")
    reason: str = Field(description="Motivazione dettagliata in italiano")

class OntologyNegotiationResponse(BaseModel):
    merges: List[MergeProposal] = []
    hierarchies: List[HierarchyProposal] = []
    links: List[LinkProposal] = []

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

def write_page_to_vault(vault_path: str, relative_path: str, content: str, frontmatter: dict = None):
    """
    Scrive direttamente una pagina nel vault specificato, creando le directory se necessario.
    """
    abs_path = os.path.join(vault_path, relative_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    if frontmatter is None:
        frontmatter = {}
    frontmatter["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not os.path.exists(abs_path) and "created_at" not in frontmatter:
        frontmatter["created_at"] = frontmatter["updated_at"]
    full_content = to_markdown(frontmatter, content)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(full_content)

def update_index_in_vault(vault_path: str, relative_page_path: str, summary: str):
    """
    Registra una pagina nel file index.md del vault specificato.
    """
    index_path = os.path.join(vault_path, "index.md")
    if not os.path.exists(index_path):
        return
        
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    basename = os.path.basename(relative_page_path)
    page_name, _ = os.path.splitext(basename)
    wikilink = f"[[{relative_page_path.replace('.md', '')}|{page_name}]]"
    
    if wikilink in content:
        return
        
    section_markers = {
        "wiki/concepts": "### 💡 [[wiki/concepts/|Concetti]]",
        "wiki/entities": "### 🏢 [[wiki/entities/|Entità]]",
        "wiki/sources": "### 📰 [[wiki/sources/|Sorgenti]]",
        "wiki/synthesis": "### 🔮 [[wiki/synthesis/|Sintesi e Riflessioni]]",
        "CRM": "### 👥 [[CRM/index|CRM Contatti]]",
    }
    
    found = False
    for folder, marker in section_markers.items():
        if relative_page_path.startswith(folder):
            if marker in content:
                new_entry = f"\n- {wikilink} — {summary}"
                content = content.replace(marker, f"{marker}{new_entry}")
                found = True
                break
                
    if found:
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(content)

def collect_nodes_metadata(vault_path: str) -> list[dict]:
    """
    Scansiona il vault per raccogliere metadati leggeri per ciascun concetto, entità e contatto CRM.
    """
    nodes = []
    search_dirs = ["wiki/concepts", "wiki/entities", "CRM"]
    for sdir in search_dirs:
        abs_sdir = os.path.join(vault_path, sdir)
        if not os.path.exists(abs_sdir):
            continue
        for root, _, files in os.walk(abs_sdir):
            for file in files:
                if file.endswith(".md") and not file.startswith("."):
                    # Escludi index.md
                    if file.lower() == "index.md":
                        continue
                        
                    abs_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_path, vault_path)
                    
                    try:
                        with open(abs_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        fm, body = parse_markdown(content)
                        
                        # Determina il tipo di default basato sulla cartella
                        if sdir == "CRM":
                            default_type = "crm_contact"
                        elif "concepts" in sdir:
                            default_type = "concept"
                        else:
                            default_type = "entity"
                            
                        node_type = fm.get("type", default_type)
                        
                        # Normalizza gli alias
                        aliases = fm.get("aliases", [])
                        if isinstance(aliases, str):
                            aliases = [aliases]
                        elif not isinstance(aliases, list):
                            aliases = []
                            
                        node_path = rel_path.replace(".md", "")
                        
                        nodes.append({
                            "path": node_path,
                            "title": file.replace(".md", ""),
                            "type": node_type,
                            "tags": fm.get("tags", []),
                            "related": fm.get("related", []),
                            "parent": fm.get("parent", None),
                            "aliases": aliases
                        })
                    except Exception:
                        pass
    return nodes

def find_fuzzy_duplicate_candidates(nodes: list[dict]) -> list[dict]:
    """
    Trova candidati duplicati (es. "Alessandro Tartaglia" e "Tartaglia") in locale.
    Utilizza SequenceMatcher per calcolare la somiglianza dei nomi/alias e
    un indice di parole significative per evitare una complessità O(N^2).
    """
    STOP_WORDS = {
        "comune", "regione", "associazione", "fondazione", "scuola", "università",
        "banca", "spi", "cgil", "corso", "via", "piazza", "viale", "lazio", "puglia",
        "bari", "napoli", "roma", "milano", "italia", "nazionale", "generale",
        "del", "della", "dello", "dei", "degli", "con", "per", "and", "the", "for",
        "d'ippolito", "di", "da", "in", "su", "il", "la", "i", "gli", "le", "un", "una"
    }
    
    word_index = {}
    
    def tokenize_name(name: str) -> set[str]:
        cleaned = re.sub(r"[^\w\s\’\']", " ", name.lower())
        tokens = cleaned.split()
        valid_tokens = set()
        for t in tokens:
            t_clean = t.strip("’'")
            if len(t_clean) >= 3 and t_clean not in STOP_WORDS:
                valid_tokens.add(t_clean)
        return valid_tokens

    def is_substring_match(name1: str, name2: str) -> bool:
        n1 = name1.lower()
        n2 = name2.lower()
        if len(n1) < 4 or len(n2) < 4:
            return False
            
        words1 = n1.split()
        words2 = n2.split()
        
        if len(words1) == 1:
            return words1[0] in words2
        if len(words2) == 1:
            return words2[0] in words1
            
        return n1 in n2 or n2 in n1

    # Popola l'indice invertito
    for idx, node in enumerate(nodes):
        names = [node["title"]] + node.get("aliases", [])
        for name in names:
            tokens = tokenize_name(name)
            for token in tokens:
                if token not in word_index:
                    word_index[token] = []
                word_index[token].append((idx, name))
                
    candidate_pairs = set()
    
    for token, occurrences in word_index.items():
        if len(occurrences) > 30:  # Salta chiavi troppo generiche
            continue
        for i in range(len(occurrences)):
            idx_a, name_a = occurrences[i]
            node_a = nodes[idx_a]
            path_a = node_a["path"]
            
            for j in range(i + 1, len(occurrences)):
                idx_b, name_b = occurrences[j]
                if idx_a == idx_b:
                    continue
                    
                node_b = nodes[idx_b]
                path_b = node_b["path"]
                
                pair_key = tuple(sorted([path_a, path_b]))
                if pair_key in candidate_pairs:
                    continue
                    
                ratio = difflib.SequenceMatcher(None, name_a.lower(), name_b.lower()).ratio()
                
                if ratio >= 0.82 or is_substring_match(name_a, name_b):
                    candidate_pairs.add(pair_key)

    candidates = []
    for path_a, path_b in candidate_pairs:
        node_a = next(n for n in nodes if n["path"] == path_a)
        node_b = next(n for n in nodes if n["path"] == path_b)
        candidates.append({
            "path_a": path_a,
            "path_b": path_b,
            "title_a": node_a["title"],
            "title_b": node_b["title"],
            "type_a": node_a["type"],
            "type_b": node_b["type"]
        })
        
    return candidates

def analyze_graph_topology(nodes: list[dict]) -> dict:
    """
    Costruisce il grafo delle relazioni (parent, related) e identifica:
    - nodi orfani (senza alcun collegamento in entrata o in uscita)
    - piccoli cluster isolati (componenti connesse di dimensione <= 3)
    """
    nodes_map = {n["path"]: n for n in nodes}
    
    title_map = {}
    for n in nodes:
        t_lower = n["title"].lower()
        if t_lower not in title_map:
            title_map[t_lower] = n["path"]
            
    def resolve_link(link_str: str) -> str:
        if not link_str:
            return None
        clean = link_str.replace("[[", "").replace("]]", "").strip()
        if "|" in clean:
            clean = clean.split("|")[0].strip()
            
        clean_no_ext, _ = os.path.splitext(clean)
        if clean_no_ext in nodes_map:
            return clean_no_ext
            
        clean_lower = clean_no_ext.lower()
        for path in nodes_map:
            if path.lower() == clean_lower:
                return path
                
        if clean_lower in title_map:
            return title_map[clean_lower]
            
        clean_base = os.path.basename(clean_no_ext).lower()
        for path in nodes_map:
            if os.path.basename(path).lower() == clean_base:
                return path
                
        return None

    adj = {n["path"]: set() for n in nodes}
    
    for n in nodes:
        u = n["path"]
        
        # Parent
        parent_resolved = resolve_link(n["parent"])
        if parent_resolved and parent_resolved in adj:
            adj[u].add(parent_resolved)
            adj[parent_resolved].add(u)
            
        # Related
        for r in n["related"]:
            r_resolved = resolve_link(r)
            if r_resolved and r_resolved in adj:
                adj[u].add(r_resolved)
                adj[r_resolved].add(u)

    visited = set()
    components = []
    
    for n in nodes:
        u = n["path"]
        if u in visited:
            continue
            
        comp = []
        queue = [u]
        visited.add(u)
        
        while queue:
            curr = queue.pop(0)
            comp.append(curr)
            for neighbor in adj[curr]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
                    
        components.append(comp)

    orphans = []
    isolated_clusters = []
    
    for comp in components:
        if len(comp) == 1:
            orphans.append(comp[0])
        elif len(comp) <= 3:
            isolated_clusters.append(comp)
            
    return {
        "orphans": orphans,
        "isolated_clusters": isolated_clusters
    }

async def generate_ontology_proposals():
    """
    Scansiona il vault e genera ontology_negotiation.md
    """
    vault_path = get_vault_path()
    nodes = collect_nodes_metadata(vault_path)
    
    if not nodes:
        print("Nessun concetto, entità o contatto trovato nel vault per l'analisi.")
        return
        
    print(f"Analisi di {len(nodes)} nodi in corso...")
    
    # 1. Esegui analisi topologica e fuzzy in locale
    fuzzy_candidates = find_fuzzy_duplicate_candidates(nodes)
    topology = analyze_graph_topology(nodes)
    orphans = topology["orphans"]
    isolated_clusters = topology["isolated_clusters"]
    
    # Calcola l'mtime di ciascun file per identificare i nodi più recentemente modificati/creati
    node_mtimes = []
    for n in nodes:
        full_path = n["path"]
        abs_file_path = os.path.join(vault_path, full_path + ".md")
        mtime = 0
        if os.path.exists(abs_file_path):
            mtime = os.path.getmtime(abs_file_path)
        node_mtimes.append((mtime, n))
        
    # Ordina i nodi per data di modifica decrescente
    node_mtimes.sort(key=lambda x: x[0], reverse=True)
    
    # Costruisci nodi per il prompt: manteniamo il path completo senza estensione come identificatore univoco
    nodes_data = []
    comp_to_full = {}
    
    # Mappa recente per i primi 120 nodi modificati di recente
    for idx, (mtime, n) in enumerate(node_mtimes):
        full_path = n["path"]
        comp_to_full[full_path] = full_path
        
        is_recent = (idx < 120)
            
        if is_recent:
            nodes_data.append({
                "path": full_path,
                "type": n["type"],
                "tags": n["tags"],
                "related": n["related"],
                "parent": n["parent"],
                "aliases": n.get("aliases", [])
            })
        else:
            nodes_data.append({
                "path": full_path,
                "type": n["type"]
            })
            
    # Filtra gli orfani recenti per non sovraccaricare il prompt
    recent_orphans = [o for o in orphans if any(o == nd["path"] for nd in nodes_data if "tags" in nd)][:50]
    
    # Prepara candidati duplicati fuzzy in formato leggibile per il prompt
    fuzzy_candidates_data = []
    for fc in fuzzy_candidates:
        fuzzy_candidates_data.append({
            "path_a": fc["path_a"],
            "title_a": fc["title_a"],
            "type_a": fc["type_a"],
            "path_b": fc["path_b"],
            "title_b": fc["title_b"],
            "type_b": fc["type_b"]
        })
        
    # Prepara cluster isolati
    isolated_clusters_data = isolated_clusters[:30] # Limita a 30
        
    settings = load_settings(vault_path)
    model = settings.get("models", {}).get("ingest_agent", "gemini-3.5-flash")
    instructions = get_agent_instructions("Ontology Agent")
    
    prompt = f"""
Di seguito trovi i dati strutturali estratti in locale per la negoziazione dell'ontologia del Secondo Cervello.

1. **Sospetti Duplicati Fuzzy (Pre-screened locali)**:
{json.dumps(fuzzy_candidates_data, indent=2, ensure_ascii=False)}

2. **Nodi Orfani Recenti (Nessuna connessione)**:
{json.dumps(recent_orphans, indent=2, ensure_ascii=False)}

3. **Cluster Isolati Recenti (Piccole componenti connesse separate dal resto del grafo)**:
{json.dumps(isolated_clusters_data, indent=2, ensure_ascii=False)}

4. **Nodi Recenti e Storici (Compresso)**:
{json.dumps(nodes_data, ensure_ascii=False)}

Analizza questi dati per formulare le proposte dell'Ontology Agent:
1. **Fusioni (merges)**: Valuta i duplicati fuzzy proposti. Se si tratta della stessa persona, entità o concetto, proponi la fusione indicando chiaramente il `source` (nodo da eliminare) e il `target` (nodo da mantenere). Se è coinvolto un contatto CRM (es. `CRM/...`), assicurati di fonderli per preservare i dettagli di contatto.
2. **Gerarchie (hierarchies)**: Trova relazioni padre-figlio ideali per connettere orfani o cluster isolati.
3. **Collegamenti (links)**: Aggiungi connessioni semantiche significative mancanti.

Restituisci esclusivamente un blocco JSON conforme a questa struttura:
```json
{{
  "merges": [
    {{"id": "M1", "source": "percorso/completo/sorgente", "target": "percorso/completo/destinazione", "reason": "Motivazione in italiano"}}
  ],
  "hierarchies": [
    {{"id": "H1", "parent": "percorso/completo/parent", "child": "percorso/completo/child", "reason": "Motivazione in italiano"}}
  ],
  "links": [
    {{"id": "L1", "source": "percorso/completo/A", "target": "percorso/completo/B", "reason": "Motivazione in italiano"}}
  ]
}}
```
Restituisci solo ed esclusivamente il blocco JSON.
"""
    
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
    
    try:
        resp_text = await call_llm_with_fallback(prompt, instructions, config)
        
        json_match = re.search(r"```json\s*(.*?)\s*```", resp_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = resp_text.strip()
            
        # Validazione strutturata tramite Pydantic
        validated_response = OntologyNegotiationResponse.model_validate(json.loads(json_str))
        merges = validated_response.merges
        hierarchies = validated_response.hierarchies
        links = validated_response.links
    except Exception as e:
        print(f"Errore durante la generazione LLM o validazione Pydantic dell'ontologia: {e}")
        if 'resp_text' in locals():
            print(f"Risposta raw:\n{resp_text}")
        return
        
    # Costruisci ontology_negotiation.md
    markdown_lines = [
        "# Ontologia Negoziale — Proposte di Sviluppo",
        "",
        "Questo file contiene le proposte di fusione, gerarchia e collegamento semantico generate dall'Ontology Agent.",
        "Apri questo file in Obsidian e spunta `[x]` le proposte che desideri approvare, oppure lascia `[ ]` per rifiutarle.",
        "Successivamente, esegui `make ontology-apply` (o chiedi ad Antigravity in chat) per applicare le modifiche.",
        "",
        "## Fusioni Proposte"
    ]
    
    def expand_path(p):
        p_strip = p.strip()
        if p_strip in comp_to_full:
            return comp_to_full[p_strip]
        # Suffix/Subpath match (case insensitive)
        p_lower = p_strip.lower()
        for k, v in comp_to_full.items():
            if k.lower() == p_lower or k.lower().endswith("/" + p_lower):
                return v
        # Basename/Title match
        p_base = os.path.basename(p_strip).lower()
        for k, v in comp_to_full.items():
            k_base = os.path.basename(k).lower()
            if k_base == p_base:
                return v
        return p_strip
        
    if merges:
        for m in merges:
            m_source = expand_path(m.source)
            m_target = expand_path(m.target)
            markdown_lines.append(f"- [ ] **[{m.id}]** Fondere [[{m_source}]] in [[{m_target}]] — Motivazione: {m.reason}")
    else:
        markdown_lines.append("Nessuna fusione proposta.")
        
    markdown_lines.append("")
    markdown_lines.append("## Gerarchie Proposte")
    
    if hierarchies:
        for h in hierarchies:
            h_parent = expand_path(h.parent)
            h_child = expand_path(h.child)
            markdown_lines.append(f"- [ ] **[{h.id}]** Impostare [[{h_parent}]] come parent di [[{h_child}]] — Motivazione: {h.reason}")
    else:
        markdown_lines.append("Nessuna gerarchia proposta.")
        
    markdown_lines.append("")
    markdown_lines.append("## Collegamenti Proposti")
    
    if links:
        for l in links:
            l_source = expand_path(l.source)
            l_target = expand_path(l.target)
            markdown_lines.append(f"- [ ] **[{l.id}]** Collegare [[{l_source}]] con [[{l_target}]] — Motivazione: {l.reason}")
    else:
        markdown_lines.append("Nessun collegamento proposto.")
        
    markdown_lines.append("")
    
    negotiation_content = "\n".join(markdown_lines)
    write_page_to_vault(vault_path, "wiki/synthesis/ontology_negotiation.md", negotiation_content, {"type": "synthesis", "purpose": "ontology_negotiation"})
    update_index_in_vault(vault_path, "wiki/synthesis/ontology_negotiation.md", "Tavolo di negoziazione dell'ontologia emergente")
    
    append_to_log("[AI Ontology] Generate nuove proposte ontologiche in [[ontology_negotiation]]")
    auto_commit(vault_path, "[AI Ontology] Generate nuove proposte ontologiche")
    print("Proposte di ontologia generate con successo in wiki/synthesis/ontology_negotiation.md.")

def approve_proposal(proposal_id: str) -> bool:
    """
    Spunta programmaticamente una proposta in ontology_negotiation.md.
    """
    vault_path = get_vault_path()
    return approve_proposal_in_vault(vault_path, proposal_id)

def approve_proposal_in_vault(vault_path: str, proposal_id: str) -> bool:
    negotiation_path = os.path.join(vault_path, "wiki/synthesis/ontology_negotiation.md")
    if not os.path.exists(negotiation_path):
        print("Errore: file ontology_negotiation.md non trovato.")
        return False
        
    with open(negotiation_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    pattern = rf"- \[ \]\s+\*\*\[{proposal_id}\]\*\*"
    if not re.search(pattern, content):
        return False
        
    new_content = re.sub(pattern, f"- [x] **[{proposal_id}]**", content)
    with open(negotiation_path, "w", encoding="utf-8") as f:
        f.write(new_content)
        
    print(f"Proposta {proposal_id} approvata programmaticamente.")
    return True

def update_links_in_vault(vault_path: str, old_path: str, new_path: str):
    """
    Aggiorna tutti i wikilink nel vault che puntano a old_path per farli puntare a new_path.
    """
    search_dirs = ["wiki", "CRM", "journal", "Meetings", "Microthemes"]
    all_files = []
    for sdir in search_dirs:
        abs_sdir = os.path.join(vault_path, sdir)
        if not os.path.exists(abs_sdir):
            continue
        for root, _, files in os.walk(abs_sdir):
            for file in files:
                if file.endswith(".md") and not file.startswith("."):
                    if file == "ontology_negotiation.md":
                        continue
                    all_files.append(os.path.join(root, file))
                    
    for f in ["index.md", "user_profile.md", "chat.md"]:
        ap = os.path.join(vault_path, f)
        if os.path.exists(ap):
            all_files.append(ap)
            
    old_basename = os.path.basename(old_path)
    new_basename = os.path.basename(new_path)
    
    escaped_old_path = re.escape(old_path)
    escaped_old_base = re.escape(old_basename)
    
    path_pattern = re.compile(rf'\[\[{escaped_old_path}(?:\|([^\]]+))?\]\]', re.IGNORECASE)
    base_pattern = re.compile(rf'\[\[{escaped_old_base}(?:\|([^\]]+))?\]\]', re.IGNORECASE)
    
    modified_count = 0
    for fpath in all_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
            
        fm, body = parse_markdown(content)
        changed = False
        
        # 1. Aggiorna la lista related nel frontmatter
        if "related" in fm and isinstance(fm["related"], list):
            new_rel = []
            for item in fm["related"]:
                if isinstance(item, str):
                    if old_path.lower() in item.lower() or old_basename.lower() in item.lower():
                        new_item = path_pattern.sub(lambda m: f"[[{new_path}]]", item)
                        new_item = base_pattern.sub(lambda m: f"[[{new_path}]]", new_item)
                        if new_item != item:
                            changed = True
                            item = new_item
                    new_rel.append(item)
                else:
                    new_rel.append(item)
            if changed:
                fm["related"] = new_rel
                
        # 2. Aggiorna la chiave parent nel frontmatter
        if "parent" in fm and isinstance(fm["parent"], str):
            val = fm["parent"]
            if old_path.lower() in val.lower() or old_basename.lower() in val.lower():
                new_val = path_pattern.sub(lambda m: f"[[{new_path}]]", val)
                new_val = base_pattern.sub(lambda m: f"[[{new_path}]]", new_val)
                if new_val != val:
                    changed = True
                    fm["parent"] = new_val
                    
        # 3. Aggiorna i wikilink nel corpo
        body_changed = False
        def replace_body_link(match):
            nonlocal body_changed
            display = match.group(1)
            body_changed = True
            if display:
                return f"[[{new_path}|{display}]]"
            else:
                return f"[[{new_path}|{new_basename}]]"
                
        new_body = path_pattern.sub(replace_body_link, body)
        new_body = base_pattern.sub(replace_body_link, new_body)
        
        if changed or body_changed:
            new_content = to_markdown(fm, new_body)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            modified_count += 1
            
    print(f"  - Aggiornati i riferimenti a {old_path} in {modified_count} file.")

def merge_nodes(vault_path: str, path_a: str, path_b: str) -> bool:
    if path_a.strip() == path_b.strip():
        print(f"Attenzione: Impossibile fondere {path_a} in se stesso.")
        return False
    abs_a = os.path.join(vault_path, path_a + ".md")
    abs_b = os.path.join(vault_path, path_b + ".md")
    if not os.path.exists(abs_a) or not os.path.exists(abs_b):
        print(f"Attenzione: Impossibile fondere {path_a} in {path_b}. Uno dei due file non esiste.")
        return False
        
    with open(abs_a, "r", encoding="utf-8") as f:
        fm_a, body_a = parse_markdown(f.read())
        
    with open(abs_b, "r", encoding="utf-8") as f:
        fm_b, body_b = parse_markdown(f.read())
        
    title_a = os.path.basename(path_a)
    title_b = os.path.basename(path_b)
    merged_body = body_b.strip() + f"\n\n### Contenuto unificato da [[{path_a}|{title_a}]]\n" + body_a.strip()
    
    # Merge tags
    tags_a = fm_a.get("tags", [])
    if isinstance(tags_a, str): tags_a = [tags_a]
    tags_b = fm_b.get("tags", [])
    if isinstance(tags_b, str): tags_b = [tags_b]
    merged_tags = list(set(tags_a + tags_b))
    
    # Merge related
    rel_a = fm_a.get("related", [])
    rel_b = fm_b.get("related", [])
    merged_related = list(set(rel_a + rel_b))
    merged_related = [r for r in merged_related if path_a not in r and path_b not in r]
    
    fm_b["tags"] = merged_tags
    fm_b["related"] = merged_related
    
    # Preserva i campi CRM (email, telefono, organizzazione, città, ruolo, note)
    crm_fields = ["email", "phone", "organization", "city", "role", "notes"]
    for field in crm_fields:
        val_a = fm_a.get(field)
        val_b = fm_b.get(field)
        if val_a and not val_b:
            fm_b[field] = val_a
        elif val_a and val_b and str(val_a).strip() != str(val_b).strip():
            fm_b[field] = f"{val_b}, {val_a}"
            
    # Unifica gli alias ed aggiunge il titolo del nodo eliminato come alias del target
    aliases_a = fm_a.get("aliases", [])
    if isinstance(aliases_a, str): aliases_a = [aliases_a]
    elif not isinstance(aliases_a, list): aliases_a = []
    
    aliases_b = fm_b.get("aliases", [])
    if isinstance(aliases_b, str): aliases_b = [aliases_b]
    elif not isinstance(aliases_b, list): aliases_b = []
    
    new_aliases = set(aliases_a + aliases_b)
    if title_a.lower() != title_b.lower():
        new_aliases.add(title_a)
    fm_b["aliases"] = list(new_aliases)
    
    # Determina il tipo corretto in base alla cartella di destinazione
    if path_b.startswith("CRM/"):
        fm_b["type"] = "crm_contact"
    elif path_b.startswith("wiki/concepts/"):
        fm_b["type"] = "concept"
    elif path_b.startswith("wiki/entities/"):
        fm_b["type"] = "entity"
        
    write_page_to_vault(vault_path, path_b + ".md", merged_body, fm_b)
    os.remove(abs_a)
    print(f"  - Fuso {path_a} in {path_b} e rimosso {path_a}.")
    
    update_links_in_vault(vault_path, path_a, path_b)
    return True

def set_parent(vault_path: str, path_parent: str, path_child: str) -> bool:
    abs_child = os.path.join(vault_path, path_child + ".md")
    if not os.path.exists(abs_child):
        print(f"Attenzione: Il file figlio {path_child} non esiste.")
        return False
        
    abs_parent = os.path.join(vault_path, path_parent + ".md")
    if not os.path.exists(abs_parent):
        print(f"Attenzione: Il file parent {path_parent} non esiste come nota markdown. Salto per evitare broken links.")
        return False
        
    with open(abs_child, "r", encoding="utf-8") as f:
        fm, body = parse_markdown(f.read())
        
    fm["parent"] = f"[[{path_parent}]]"
    write_page_to_vault(vault_path, path_child + ".md", body, fm)
    print(f"  - Impostato parent di {path_child} -> [[{path_parent}]]")
    return True

def connect_nodes(vault_path: str, path_a: str, path_b: str) -> bool:
    abs_a = os.path.join(vault_path, path_a + ".md")
    abs_b = os.path.join(vault_path, path_b + ".md")
    if not os.path.exists(abs_a) or not os.path.exists(abs_b):
        print(f"Attenzione: Impossibile collegare {path_a} e {path_b}. Uno dei due file non esiste.")
        return False
        
    # Connect A -> B
    with open(abs_a, "r", encoding="utf-8") as f:
        fm_a, body_a = parse_markdown(f.read())
    rel_a = fm_a.get("related", [])
    if f"[[{path_b}]]" not in rel_a:
        rel_a.append(f"[[{path_b}]]")
        fm_a["related"] = rel_a
        write_page_to_vault(vault_path, path_a + ".md", body_a, fm_a)
        
    # Connect B -> A
    with open(abs_b, "r", encoding="utf-8") as f:
        fm_b, body_b = parse_markdown(f.read())
    rel_b = fm_b.get("related", [])
    if f"[[{path_a}]]" not in rel_b:
        rel_b.append(f"[[{path_a}]]")
        fm_b["related"] = rel_b
        write_page_to_vault(vault_path, path_b + ".md", body_b, fm_b)
        
    print(f"  - Collegati bidirezionalmente {path_a} <-> {path_b}")
    return True

def apply_negotiated_ontology():
    """
    Legge ontology_negotiation.md ed esegue tutte le modifiche approvate (spuntate).
    """
    vault_path = get_vault_path()
    apply_negotiated_ontology_in_vault(vault_path)

def apply_negotiated_ontology_in_vault(vault_path: str):
    negotiation_path = os.path.join(vault_path, "wiki/synthesis/ontology_negotiation.md")
    if not os.path.exists(negotiation_path):
        print("Nessun tavolo di negoziazione (ontology_negotiation.md) trovato.")
        return
        
    with open(negotiation_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    new_lines = []
    actions_count = 0
    
    merge_re = re.compile(r'- \[x\] \*\*\[(M\d+)\]\*\* Fondere \[\[([^\]|]+)(?:\|[^\]]*)?\]\] in \[\[([^\]|]+)(?:\|[^\]]*)?\]\]')
    hierarchy_re = re.compile(r'- \[x\] \*\*\[(H\d+)\]\*\* Impostare \[\[([^\]|]+)(?:\|[^\]]*)?\]\] come parent di \[\[([^\]|]+)(?:\|[^\]]*)?\]\]')
    link_re = re.compile(r'- \[x\] \*\*\[(L\d+)\]\*\* Collegare \[\[([^\]|]+)(?:\|[^\]]*)?\]\] con \[\[([^\]|]+)(?:\|[^\]]*)?\]\]')
    
    print("Applicazione delle proposte ontologiche approvate...")
    
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        if "(Applicata)" in stripped:
            new_lines.append(line)
            i += 1
            continue
            
        m_match = merge_re.match(stripped)
        h_match = hierarchy_re.match(stripped)
        l_match = link_re.match(stripped)
        
        if m_match:
            pid, source, target = m_match.groups()
            print(f"Esecuzione Fusione [{pid}]: {source} -> {target}")
            success = merge_nodes(vault_path, source.strip(), target.strip())
            if success:
                actions_count += 1
                line = line.replace(f"- [x] **[{pid}]**", f"- [x] **[{pid}]** (Applicata)")
                # Rimuove le parentesi quadre dal link del sorgente eliminato (gestendo eventuali pipe)
                line = re.sub(rf'\[\[{re.escape(source)}(?:\|([^\]]+))?\]\]', lambda m: m.group(1) if m.group(1) else source, line)
                # Aggiorna anche le linee successive in memoria per evitare link rotti verso il file eliminato
                for j in range(i + 1, len(lines)):
                    lines[j] = re.sub(
                        rf'\[\[{re.escape(source)}(\|[^\]]+)?\]\]',
                        lambda m: f"[[{target}{m.group(1)}]]" if m.group(1) else f"[[{target}]]",
                        lines[j]
                    )
                
        elif h_match:
            pid, parent_path, child_path = h_match.groups()
            print(f"Esecuzione Gerarchia [{pid}]: parent {parent_path} di {child_path}")
            success = set_parent(vault_path, parent_path.strip(), child_path.strip())
            if success:
                actions_count += 1
                line = line.replace(f"- [x] **[{pid}]**", f"- [x] **[{pid}]** (Applicata)")
                
        elif l_match:
            pid, source, target = l_match.groups()
            print(f"Esecuzione Collegamento [{pid}]: {source} <-> {target}")
            success = connect_nodes(vault_path, source.strip(), target.strip())
            if success:
                actions_count += 1
                line = line.replace(f"- [x] **[{pid}]**", f"- [x] **[{pid}]** (Applicata)")
                
        new_lines.append(line)
        i += 1
        
    if actions_count > 0:
        with open(negotiation_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
            
        # If it's the real vault, log and commit
        if vault_path == get_vault_path():
            append_to_log(f"[AI Ontology] Applicate {actions_count} decisioni ontologiche negoziate.")
            auto_commit(vault_path, f"[AI Ontology] Applicate {actions_count} decisioni ontologiche")
        print(f"Applicazione completata con successo: {actions_count} modifiche effettuate.")
    else:
        print("Nessuna nuova proposta approvata (spuntata con [x]) da applicare.")

if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "--generate"
    if action == "--apply":
        apply_negotiated_ontology()
    elif action == "--approve" and len(sys.argv) > 2:
        approve_proposal(sys.argv[2])
    else:
        asyncio.run(generate_ontology_proposals())
