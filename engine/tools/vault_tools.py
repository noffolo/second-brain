import os
import glob
import json
import datetime
from engine.utils.markdown import parse_markdown, to_markdown

def get_vault_path() -> str:
    """Returns the absolute path of the second_brain vault."""
    # Since this file is in engine/tools/, the vault path is 2 levels up
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def get_processed_manifest_path() -> str:
    return os.path.join(get_vault_path(), "engine", "processed_files.json")

def load_processed_files() -> dict[str, float]:
    path = get_processed_manifest_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return {p: 0.0 for p in data}
            elif isinstance(data, dict):
                return data
            return {}
    except Exception:
        return {}

def save_processed_file(relative_path: str):
    path = get_processed_manifest_path()
    processed = load_processed_files()
    
    # Prendi l'mtime corrente del file da registrare
    abs_path = os.path.join(get_vault_path(), relative_path)
    mtime = 0.0
    if os.path.exists(abs_path):
        mtime = os.path.getmtime(abs_path)
        
    processed[relative_path] = mtime
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(processed, f, indent=4)
    except Exception as e:
        print(f"Errore nel salvare il manifest: {e}")

def save_processed_files_batch(relative_paths: list[str]):
    path = get_processed_manifest_path()
    processed = load_processed_files()
    
    vault_path = get_vault_path()
    for rel_path in relative_paths:
        abs_path = os.path.join(vault_path, rel_path)
        mtime = 0.0
        if os.path.exists(abs_path):
            mtime = os.path.getmtime(abs_path)
        processed[rel_path] = mtime
        
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(processed, f, indent=4)
    except Exception as e:
        print(f"Errore nel salvare il manifest in batch: {e}")

def read_raw_file(relative_path: str) -> str:
    """
    Legge il contenuto di un file sorgente in raw/ o di un verbale in Meetings/.
    
    Args:
        relative_path: Il percorso del file relativo al vault (es. 'raw/manual/nota.md').
    """
    abs_path = os.path.join(get_vault_path(), relative_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"File raw '{relative_path}' non trovato.")
    with open(abs_path, "r", encoding="utf-8") as f:
        return f.read()

def write_wiki_page(relative_path: str, content: str, frontmatter: dict = None) -> str:
    """
    Crea o aggiorna una pagina nel wiki con il relativo frontmatter.
    
    Args:
        relative_path: Percorso del file wiki relativo al vault (es. 'wiki/concepts/AI.md').
        content: Il corpo markdown della pagina.
        frontmatter: Un dizionario contenente i metadati YAML.
    """
    abs_path = os.path.join(get_vault_path(), relative_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    
    if frontmatter is None:
        frontmatter = {}
        
    # Standard metadata
    frontmatter["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not os.path.exists(abs_path) and "created_at" not in frontmatter:
        frontmatter["created_at"] = frontmatter["updated_at"]
        
    full_content = to_markdown(frontmatter, content)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(full_content)
        
    return f"Pagina wiki scritta correttamente in {relative_path}."

def update_frontmatter(relative_path: str, updates: dict) -> str:
    """
    Aggiorna selettivamente i campi del frontmatter di una pagina esistente.
    """
    abs_path = os.path.join(get_vault_path(), relative_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"Impossibile aggiornare il frontmatter: '{relative_path}' non esiste.")
        
    with open(abs_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    fm, body = parse_markdown(content)
    fm.update(updates)
    fm["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    full_content = to_markdown(fm, body)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(full_content)
        
    return f"Frontmatter di {relative_path} aggiornato."

def append_to_log(entry: str):
    """
    Aggiunge una riga di log cronologica a log.md.
    """
    log_path = os.path.join(get_vault_path(), "log.md")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    log_line = f"- **{timestamp}**: {entry}\n"
    
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(log_line)

_index_cache = None

def update_index(relative_page_path: str, summary: str):
    """
    Registra una pagina wiki (concetto, entità o sorgente) in index.md.
    """
    global _index_cache
    index_path = os.path.join(get_vault_path(), "index.md")
    if not os.path.exists(index_path):
        return
        
    if _index_cache is None:
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                _index_cache = f.read()
        except Exception as e:
            print(f"[update_index] Errore di lettura index.md: {e}")
            return
        
    # Generate wikilink name
    basename = os.path.basename(relative_page_path)
    page_name, _ = os.path.splitext(basename)
    wikilink = f"[[{relative_page_path.replace('.md', '')}|{page_name}]]"
    
    # Check if page is already in index
    if wikilink in _index_cache:
        return
        
    # Append to the right section based on folder
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
            if marker in _index_cache:
                new_entry = f"\n- {wikilink} — {summary}"
                _index_cache = _index_cache.replace(marker, f"{marker}{new_entry}")
                found = True
                break
                
    if found:
        try:
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(_index_cache)
        except Exception as e:
            print(f"[update_index] Errore di scrittura index.md: {e}")

def search_wiki(query: str) -> list[dict]:
    """
    Effettua una ricerca testuale (case-insensitive) all'interno di tutti i file markdown del wiki
    utilizzando `git grep --no-index` e estrazione veloce del testo per massimizzare le performance.
    I risultati sono ordinati per pertinenza rispetto al titolo della nota.
    """
    import subprocess
    vault = get_vault_path()
    results = []
    
    if not query.strip():
        return results
        
    query_lower = query.lower()
    
    # Sistema di scoring pertinenza
    def get_priority_score(rel_path: str) -> int:
        filename = os.path.basename(rel_path).lower()
        title = os.path.splitext(filename)[0]
        # Match esatto del titolo
        if title == query_lower:
            return 100
        # Il titolo inizia con la query
        if title.startswith(query_lower):
            return 80
        # La query è contenuta nel titolo
        if query_lower in title:
            return 60
        # La query è nel percorso/cartelle
        if query_lower in rel_path.lower():
            return 40
        return 0

    try:
        # Comando git grep ultra-rapido
        cmd = [
            "git", "grep",
            "--no-index",
            "-I", "-i", "-l", "-F",
            "-e", query,
            "--", "*.md"
        ]
        
        res = subprocess.run(
            cmd,
            cwd=vault,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8"
        )
        
        if res.returncode == 0:
            matching_files = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            
            # Filtra subito per cartelle permesse
            allowed_files = []
            for rel_filepath in matching_files:
                allowed = False
                for sdir in ["wiki", "CRM", "journal", "Meetings", "Microthemes", "raw"]:
                    if rel_filepath.startswith(sdir + "/") or rel_filepath.startswith(sdir + "\\"):
                        allowed = True
                        break
                if allowed:
                    allowed_files.append(rel_filepath)
            
            # Ordina per score di pertinenza
            allowed_files.sort(key=get_priority_score, reverse=True)
            
            # Leggi i file ordinati fino al limite desiderato
            for rel_filepath in allowed_files:
                if len(results) >= 20:
                    break
                    
                abs_filepath = os.path.join(vault, rel_filepath)
                if not os.path.exists(abs_filepath):
                    continue
                    
                try:
                    with open(abs_filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    # Estrazione ultra-veloce del body senza fare il parsing YAML/Markdown
                    if content.startswith("---"):
                        parts = content.split("---", 2)
                        body = parts[2] if len(parts) >= 3 else content
                    else:
                        body = content
                    
                    body_clean = body.strip()
                    title = os.path.splitext(os.path.basename(rel_filepath))[0]
                    results.append({
                        "path": rel_filepath,
                        "title": title,
                        "snippet": body_clean[:200] + "..." if len(body_clean) > 200 else body_clean
                    })
                except Exception:
                    pass
            return results
            
    except Exception as e:
        print(f"Errore durante l'esecuzione di git grep: {e}. Fallback su scansione lineare.")

    # Fallback a scansione lineare originale ordinata per rilevanza
    search_dirs = ["wiki", "CRM", "journal", "Meetings", "Microthemes", "raw"]
    temp_results = []
    for sdir in search_dirs:
        abs_sdir = os.path.join(vault, sdir)
        if not os.path.exists(abs_sdir):
            continue
        for root, _, files in os.walk(abs_sdir):
            for file in files:
                if file.endswith(".md"):
                    abs_filepath = os.path.join(root, file)
                    rel_filepath = os.path.relpath(abs_filepath, vault)
                    try:
                        with open(abs_filepath, "r", encoding="utf-8") as f:
                            content = f.read()
                        if query.lower() in content.lower():
                            if content.startswith("---"):
                                parts = content.split("---", 2)
                                body = parts[2] if len(parts) >= 3 else content
                            else:
                                body = content
                            body_clean = body.strip()
                            temp_results.append({
                                "path": rel_filepath,
                                "title": file.replace(".md", ""),
                                "snippet": body_clean,
                                "score": get_priority_score(rel_filepath)
                            })
                    except Exception:
                        pass
                        
    temp_results.sort(key=lambda x: x["score"], reverse=True)
    for r in temp_results[:20]:
        body_clean = r["snippet"]
        results.append({
            "path": r["path"],
            "title": r["title"],
            "snippet": body_clean[:200] + "..." if len(body_clean) > 200 else body_clean
        })
    return results

def list_unprocessed_raw() -> list[str]:
    """
    Elenca tutti i file in raw/ (e opzionalmente verbali nuovi in Meetings/) 
    che non sono ancora stati processati o che sono stati modificati dall'ultima elaborazione,
    ordinati per priorità.
    """
    vault = get_vault_path()
    processed = load_processed_files()
    unprocessed = []
    
    def needs_processing(rel_path: str, abs_path: str) -> bool:
        if rel_path not in processed:
            return True
        # Se presente in processed, controlla se l'mtime corrente è maggiore di quello salvato.
        # Aggiungiamo un piccolo margine di tolleranza di 1.0 secondo.
        recorded_mtime = processed.get(rel_path, 0.0)
        try:
            current_mtime = os.path.getmtime(abs_path)
            return current_mtime > (recorded_mtime + 1.0)
        except Exception:
            return False
            
    # 1. Check raw/ folder
    raw_dir = os.path.join(vault, "raw")
    for root, dirs, files in os.walk(raw_dir):
        # Salta la cartella degli allegati binari in quanto gestiti internamente ai markdown delle mail
        if "mail_attachments" in root:
            continue
        for file in files:
            # Skip hidden files and .gitkeep
            if file.startswith(".") or file == ".gitkeep":
                continue
            abs_path = os.path.join(root, file)
            rel_path = os.path.relpath(abs_path, vault)
            rel_path_norm = rel_path.replace("\\", "/")
            # Salta i file WhatsApp originali (es. Chat_FF3300.txt) per elaborare solo i chunk mensili
            if rel_path_norm.startswith("raw/whatsapp/") and not rel_path_norm.startswith("raw/whatsapp/chunks/"):
                continue
            if needs_processing(rel_path, abs_path):
                unprocessed.append(rel_path)
                
    # 2. Check Meetings/ folder (for meeting-agent integration)
    meetings_dir = os.path.join(vault, "Meetings")
    if os.path.exists(meetings_dir):
        for root, _, files in os.walk(meetings_dir):
            for file in files:
                if file.startswith(".") or file == ".gitkeep" or not file.endswith(".md"):
                    continue
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, vault)
                if needs_processing(rel_path, abs_path):
                    unprocessed.append(rel_path)
                    
    # Ordinamento per priorità per evitare blocchi causati da dump storici enormi
    def get_priority(path: str) -> int:
        path_norm = path.replace("\\", "/")
        if path_norm.startswith("raw/manual/"):
            return 1
        if path_norm.startswith("raw/whatsapp/"):
            return 2
        if path_norm.startswith("Meetings/"):
            return 3
        if path_norm.startswith("raw/mail/"):
            return 4
        if path_norm.startswith("raw/web_articles/"):
            return 5
        if path_norm.startswith("raw/calendar/"):
            return 20
        if path_norm.startswith("raw/notion/"):
            return 21
        if path_norm.startswith("raw/tasks/"):
            return 22
        if "raw/archive_v" in path_norm:  # Archivi storici
            return 100
        return 10  # Default per altro
        
    unprocessed.sort(key=get_priority)
    return unprocessed

def create_wiki_page_tool(title: str, category: str, content: str, tags: list = None) -> str:
    """
    Crea una nuova nota/pagina informativa nel wiki locale del Secondo Cervello.
    
    Args:
        title: Il titolo della pagina (es. 'Architettura Transformatore', 'Mario Rossi').
        category: La categoria della nota (deve essere 'concepts', 'entities' o 'sources').
        content: Il contenuto in formato markdown.
        tags: Una lista opzionale di tag associati (es. ['AI', 'deep-learning']).
    """
    import re
    from engine.utils.markdown import to_markdown
    
    vault_path = get_vault_path()
    
    # Validazione categoria
    category_lower = category.lower().strip()
    if category_lower not in ["concepts", "entities", "sources"]:
        return "Errore: La categoria deve essere una tra 'concepts', 'entities', o 'sources'."
        
    # Sanitizzazione titolo e percorso
    clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    if not clean_title:
        return "Errore: Il titolo fornito non è valido."
        
    relative_path = f"wiki/{category_lower}/{clean_title}.md"
    abs_path = os.path.join(vault_path, relative_path)
    
    if os.path.exists(abs_path):
        return f"Nota esistente: Una pagina con titolo '{title}' esiste già in `{relative_path}`."
        
    # Costruisci frontmatter standard
    fm = {
        "title": title,
        "type": "concept" if category_lower == "concepts" else ("entity" if category_lower == "entities" else "source"),
        "tags": tags or [],
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Costruisci corpo markdown
    body = f"# {title}\n\n{content.strip()}\n"
    
    full_md = to_markdown(fm, body)
    
    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(full_md)
            
        # Auto-commit su Git se configurato
        try:
            from engine.git_ops import git_commit_file
            git_commit_file(relative_path, f"Crea nota: {title}")
        except Exception:
            pass
            
        return f"Nota '{title}' creata con successo nel wiki in `{relative_path}`."
    except Exception as e:
        return f"Errore durante la creazione della nota locale: {e}"
