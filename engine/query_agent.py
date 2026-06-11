import os
import re
import time
import asyncio
from google.antigravity import Agent, LocalAgentConfig
from engine.utils.markdown import load_settings, parse_markdown
from engine.tools.vault_tools import get_vault_path, search_wiki, append_to_log, create_wiki_page_tool
from engine.tools.notion_tasks import create_notion_task
from engine.git_ops import auto_commit

# Custom tool for agent
def read_wiki_page_content(relative_path: str) -> str:
    """
    Legge il contenuto di qualsiasi pagina markdown nel vault (concetti, entità, sorgenti o diari).
    
    Args:
        relative_path: Il percorso relativo al vault (es. 'wiki/concepts/AI.md').
    """
    vault = get_vault_path()
    abs_path = os.path.join(vault, relative_path)
    if not os.path.exists(abs_path):
        return f"File '{relative_path}' non trovato."
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Errore durante la lettura del file: {e}"

def extract_keywords(query: str) -> list[str]:
    """Estrae parole chiave significative per la ricerca testuale, escludendo le stopwords."""
    words = re.findall(r'\w+', query.lower())
    stopwords = {
        "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
        "e", "o", "ma", "se", "che", "del", "dello", "della", "dei", "degli", "delle", "al", "allo", "alla", "ai", "agli",
        "alle", "dal", "dallo", "dalla", "dai", "dagli", "dalle", "nel", "nello", "nella", "nei", "negli", "nelle", "sul",
        "sullo", "sulla", "sui", "sugli", "sulle", "col", "coi", "cosa", "come", "dove", "quando", "perche", "chi", "quale",
        "quali", "questo", "quello", "mi", "ti", "ci", "vi", "si", "lo", "la", "li", "le", "gli", "ne", "su", "per",
        "assoluto", "quello", "quelli", "quella", "questo", "questi", "questa", "sono", "stato", "stati", "era", "erano",
        "ff3300"
    }
    keywords = []
    for w in words:
        w_clean = w.strip("’'")
        if len(w_clean) >= 3 and w_clean not in stopwords:
            stem = w_clean
            if w_clean[-1] in 'oaiei' and len(w_clean) > 4:
                stem = w_clean[:-1]
            if stem not in keywords:
                keywords.append(stem)
    return keywords

def expand_with_graph_neighbors(results: list[dict], vault_path: str, max_neighbors: int = 5) -> list[dict]:
    """
    Espande i risultati della ricerca includendo i frammenti delle note collegate (vicini di primo grado)
    per fornire un contesto Graph RAG ricco.
    """
    from engine.utils.markdown import extract_wikilinks
    expanded = list(results)
    seen_paths = {r['path'] for r in results}
    
    # Raccoglie i link dai primi 3 risultati più rilevanti
    neighbors_to_fetch = []
    for r in results[:3]:
        filepath = os.path.join(vault_path, r['path'])
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                links = extract_wikilinks(content)
                for link in links:
                    # Rimuove l'estensione o i pipe dal link se presenti
                    clean_link = link.split("|")[0].replace(".md", "").strip()
                    neighbors_to_fetch.append((r['path'], clean_link))
            except Exception:
                pass
                
    # Risolve i vicini e aggiunge i loro frammenti
    resolved_count = 0
    from engine.ingest_agent import load_aliases_map
    aliases_map = load_aliases_map(vault_path)
    
    for parent_path, link in neighbors_to_fetch:
        if resolved_count >= max_neighbors:
            break
            
        link_lower = link.lower()
        entry = aliases_map.get(link_lower)
        if entry:
            rel_path = entry["path"]
            if rel_path not in seen_paths:
                seen_paths.add(rel_path)
                abs_path = os.path.join(vault_path, rel_path)
                if os.path.exists(abs_path):
                    try:
                        with open(abs_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        _, body = parse_markdown(content)
                        body_clean = body.strip()
                        snippet = body_clean[:400] + "..." if len(body_clean) > 400 else body_clean
                        expanded.append({
                            "path": rel_path,
                            "title": entry["canonical"],
                            "snippet": f"[Nota correlata collegata a [[{parent_path.replace('.md', '')}]]]:\n{snippet}"
                        })
                        resolved_count += 1
                    except Exception:
                        pass
                        
    return expanded

async def run_git_grep(kw: str, vault_path: str, folders: list[str]) -> set[str]:
    if not folders:
        return set()
    cmd = ["git", "grep", "--no-index", "-I", "-i", "-l", "-F", "-e", kw, "--"] + folders
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=vault_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return {line.strip() for line in stdout.decode("utf-8", errors="ignore").splitlines() if line.strip()}
    except Exception as e:
        print(f"[git-grep] Errore per {kw}: {e}")
    return set()

async def run_vector_search(query: str, limit: int):
    try:
        from engine.utils.vector_db import get_vector_db
        db = get_vector_db()
        return await asyncio.to_thread(db.search_similar, query, limit)
    except Exception as e:
        print(f"[Vector Search] Errore: {e}")
        return []

async def run_keyword_search(kw: str):
    try:
        return await asyncio.to_thread(search_wiki, kw)
    except Exception as e:
        print(f"[Keyword Search] Errore per {kw}: {e}")
        return []

async def hybrid_search_vault_func(query: str, limit: int = 15) -> list[dict]:
    """
    Esegue una ricerca ibrida unendo i risultati semantici del Vector DB
    con la ricerca testuale classica (search_wiki) basata su parole chiave.
    Espande poi i risultati includendo le note adiacenti nel grafo (Graph RAG).
    """
    keywords = extract_keywords(query)
    vault = get_vault_path()
    existing_folders = [d for d in ["wiki", "CRM", "journal", "Meetings", "Microthemes"] if os.path.exists(os.path.join(vault, d))]
    
    tasks = []
    
    # 0. Ricerca per intersezione di parole chiave (AND) via git grep concorrente
    and_task = None
    if len(keywords) > 1:
        async def run_and_search():
            grep_tasks = [run_git_grep(kw, vault, existing_folders) for kw in keywords[:3]]
            file_sets = await asyncio.gather(*grep_tasks)
            if file_sets:
                return set.intersection(*file_sets)
            return set()
        and_task = asyncio.create_task(run_and_search())
        tasks.append(and_task)
        
    # 1. Ricerca Vettoriale Semantica
    vector_task = asyncio.create_task(run_vector_search(query, limit))
    tasks.append(vector_task)
    
    # 2. Ricerca Testuale Classica
    keyword_tasks = [asyncio.create_task(run_keyword_search(kw)) for kw in keywords[:3]]
    tasks.extend(keyword_tasks)
    
    # Esegue tutte le ricerche in parallelo
    await asyncio.gather(*tasks, return_exceptions=True)
    
    seen_paths = set()
    results = []
    
    # Raccoglie i risultati di AND search (priorità massima)
    if and_task:
        try:
            intersected = and_task.result()
            for rel_filepath in intersected:
                rel_filepath = rel_filepath.replace("\\", "/")
                if rel_filepath not in seen_paths:
                    seen_paths.add(rel_filepath)
                    abs_filepath = os.path.join(vault, rel_filepath)
                    if os.path.exists(abs_filepath):
                        try:
                            with open(abs_filepath, "r", encoding="utf-8") as f:
                                content = f.read()
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
                                "snippet": body_clean[:400] + "..." if len(body_clean) > 400 else body_clean
                            })
                        except Exception:
                            pass
                        if len(results) >= limit:
                            break
        except Exception as e:
            print(f"[Hybrid Search] Errore recupero AND: {e}")
            
    # Raccoglie i risultati di ricerca vettoriale
    try:
        vec_results = vector_task.result()
        for r in vec_results:
            if r.get('distance', 0) > 1.15:
                continue
            path_clean = r['path'].replace("\\", "/")
            if path_clean not in seen_paths:
                seen_paths.add(path_clean)
                results.append({
                    "path": path_clean,
                    "title": r['title'],
                    "snippet": r['snippet']
                })
            if len(results) >= limit:
                break
    except Exception as e:
        print(f"[Hybrid Search] Errore recupero vettoriale: {e}")
        
    # Raccoglie i risultati keyword
    for kt in keyword_tasks:
        if len(results) >= limit:
            break
        try:
            kw_results = kt.result()
            kw = keywords[keyword_tasks.index(kt)]
            for r in kw_results:
                path_clean = r['path'].replace("\\", "/")
                if path_clean not in seen_paths:
                    filepath = os.path.join(vault, path_clean)
                    snippet = r.get('snippet', '')
                    if os.path.exists(filepath):
                        try:
                            with open(filepath, "r", encoding="utf-8") as f_read:
                                body = f_read.read(1200)
                                if body.strip():
                                    snippet = body.strip()
                        except Exception:
                            pass
                            
                        # Filtro anti-rumore per query multi-parola
                        is_relevant = True
                        if len(keywords) >= 2:
                            capitalized_words = {w.strip("’'").lower() for w in query.split() if w and w[0].isupper()}
                            query_words = query.split()
                            if query_words and query_words[0][0].isupper() and len(capitalized_words) > 1:
                                capitalized_words.discard(query_words[0].strip("’'").lower())
                            capitalized_words.discard("ff3300")
                            
                            in_title = kw.lower() in r['title'].lower()
                            is_proper_noun = kw.lower() in capitalized_words
                            
                            if not in_title and not is_proper_noun:
                                if capitalized_words:
                                    body_lower = snippet.lower()
                                    title_lower = r['title'].lower()
                                    has_proper_match = any(pw in body_lower or pw in title_lower for pw in capitalized_words)
                                    if not has_proper_match:
                                        is_relevant = False
                                else:
                                    other_kws = [k.lower() for k in keywords if k != kw and len(k) >= 4]
                                    if not other_kws:
                                        other_kws = [k.lower() for k in keywords if k != kw]
                                    body_lower = snippet.lower()
                                    title_lower = r['title'].lower()
                                    has_other_match = any(okw in body_lower or okw in title_lower for okw in other_kws)
                                    if not has_other_match:
                                        is_relevant = False
                                    
                        if not is_relevant:
                            continue
                            
                        seen_paths.add(path_clean)
                        results.append({
                            "path": path_clean,
                            "title": r['title'],
                            "snippet": snippet
                        })
                    if len(results) >= limit:
                        break
        except Exception as e:
            print(f"[Hybrid Search] Errore recupero keyword per {kw}: {e}")
            
    # 3. Espansione dei vicini del grafo (Graph RAG)
    try:
        results = expand_with_graph_neighbors(results, vault, max_neighbors=5)
    except Exception as e:
        print(f"[Graph RAG] Errore espansione vicini: {e}")
        
    return results[:limit]

async def search_vault(query: str) -> str:
    """
    Cerca nel vault le note più pertinenti alla query utilizzando un approccio ibrido
    (ricerca semantica vettoriale combinata con ricerca testuale su parole chiave).
    Usa questo strumento per trovare concetti, fatti, o memorie passate sia per significato che per parole chiave.
    Ritorna i frammenti di testo più rilevanti estratti dai documenti.
    """
    try:
        results = await hybrid_search_vault_func(query, limit=10)
        if not results:
            return "Nessun risultato trovato nel vault."
        out = []
        for r in results:
            out.append(f"--- Nota: {r['path']} (Titolo: {r['title']}) ---\n{r['snippet']}\n")
        return "\n".join(out)
    except Exception as e:
        return f"Errore ricerca ibrida: {e}"

_stats_cache = {"time": 0, "data": ""}

def get_second_brain_statistics() -> str:
    """
    Ritorna statistiche aggregate del Secondo Cervello, come il numero di riunioni per anno,
    la classifica dei clienti con cui si sono fatte più riunioni in assoluto,
    il numero totale di progetti (completati e attivi), il numero di clienti, task e documenti.
    Usa questo strumento per rispondere a domande quantitative, aggregazioni, conteggi, classifiche o riassuntive sui dati strutturati (es. riunioni per anno, classifica clienti per riunioni, progetti attivi, clienti).
    """
    global _stats_cache
    if time.time() - _stats_cache["time"] < 300:  # 5 minutes TTL
        return _stats_cache["data"]

    vault = get_vault_path()
    
    # 1. Riunioni per anno e classifica dei clienti
    meetings_by_year = {}
    meetings_by_client = {}
    seen_notion_ids = set()
    
    riunioni_dir = os.path.join(vault, "wiki", "sources", "Riunioni")
    fallback_dir = os.path.join(vault, "raw", "calendar")
    
    dirs_to_check = []
    if os.path.exists(riunioni_dir):
        dirs_to_check.append(riunioni_dir)
    if os.path.exists(fallback_dir):
        dirs_to_check.append(fallback_dir)
        
    for m_dir in dirs_to_check:
        for root, _, files in os.walk(m_dir):
            for f in files:
                if f.endswith(".md") and not f.startswith("."):
                    try:
                        filepath = os.path.join(root, f)
                        with open(filepath, "r", encoding="utf-8") as file_f:
                            content = file_f.read()
                            
                        fm, _ = parse_markdown(content)
                        if not fm:
                            continue
                            
                        # Evita il doppio conteggio tracciando notion_page_id
                        n_id = fm.get("notion_page_id")
                        if n_id:
                            if n_id in seen_notion_ids:
                                continue
                            seen_notion_ids.add(n_id)
                            
                        # Estrazione dell'anno
                        year = None
                        quando = fm.get("quando")
                        if quando:
                            quando_str = str(quando).strip()
                            if len(quando_str) >= 4 and quando_str[:4].isdigit():
                                year = quando_str[:4]
                                
                        if not year:
                            start_time = fm.get("start_time")
                            if start_time:
                                start_time_str = str(start_time).strip()
                                if len(start_time_str) >= 4 and start_time_str[:4].isdigit():
                                    year = start_time_str[:4]
                                    
                        if not year:
                            match_quando = re.search(r"Quando\?:\s*['\"]?(\d{4})", content)
                            if match_quando:
                                year = match_quando.group(1)
                                
                        if year:
                            meetings_by_year[year] = meetings_by_year.get(year, 0) + 1
                            
                        # Estrazione del cliente
                        cliente_data = fm.get("cliente") or fm.get("clienti")
                        if cliente_data:
                            if isinstance(cliente_data, str):
                                clients = [cliente_data]
                            elif isinstance(cliente_data, list):
                                clients = cliente_data
                            else:
                                clients = []
                                
                            for c in clients:
                                if isinstance(c, str):
                                    # Pulisci markup wikilink
                                    clean_c = c.replace("[[", "").replace("]]", "").strip()
                                    if clean_c:
                                        meetings_by_client[clean_c] = meetings_by_client.get(clean_c, 0) + 1
                    except Exception:
                        pass
                        
    # 2. Progetti
    projects_dir = os.path.join(vault, "wiki", "entities", "Progetti")
    total_projects = 0
    active_projects = 0
    completed_projects = 0
    projects_by_client = {}
    if os.path.exists(projects_dir):
        for root, _, files in os.walk(projects_dir):
            for f in files:
                if f.endswith(".md") and not f.startswith("."):
                    total_projects += 1
                    try:
                        filepath = os.path.join(root, f)
                        with open(filepath, "r", encoding="utf-8") as file_f:
                            content = file_f.read()
                        fm, _ = parse_markdown(content)
                        is_completed = False
                        if fm:
                            is_completed = fm.get("completato") is True or str(fm.get("completato")).lower() == "true"
                            if not is_completed:
                                if "completato?: true" in content.lower() or "completato: true" in content.lower():
                                    is_completed = True
                        else:
                            if "completato?: true" in content.lower() or "completato: true" in content.lower():
                                is_completed = True
                                
                        if is_completed:
                            completed_projects += 1
                        else:
                            active_projects += 1
                            
                        # Aggrega progetti per cliente
                        if fm:
                            cliente_data = fm.get("cliente") or fm.get("clienti")
                            if cliente_data:
                                if isinstance(cliente_data, str):
                                    clients = [cliente_data]
                                elif isinstance(cliente_data, list):
                                    clients = cliente_data
                                else:
                                    clients = []
                                for c in clients:
                                    if isinstance(c, str):
                                        clean_c = c.replace("[[", "").replace("]]", "").strip()
                                        if clean_c:
                                            projects_by_client[clean_c] = projects_by_client.get(clean_c, 0) + 1
                    except Exception:
                        pass

    # 3. Clienti
    clienti_dir = os.path.join(vault, "wiki", "entities", "Clienti")
    total_clients = 0
    in_essere_clients = 0
    if os.path.exists(clienti_dir):
        for root, _, files in os.walk(clienti_dir):
            for f in files:
                if f.endswith(".md") and not f.startswith("."):
                    total_clients += 1
                    try:
                        with open(os.path.join(root, f), "r", encoding="utf-8") as file_f:
                            content = file_f.read(800)
                        if "incarico_in_essere?: true" in content.lower():
                            in_essere_clients += 1
                    except Exception:
                        pass

    # 4. Task
    task_dir = os.path.join(vault, "wiki", "entities", "Task")
    total_tasks = 0
    tasks_by_status = {}
    completed_tasks_by_client = {}
    
    # Per risalire al cliente dal progetto se manca nella task
    project_to_clients = {}
    if os.path.exists(projects_dir):
        for root, _, files in os.walk(projects_dir):
            for f in files:
                if f.endswith(".md") and not f.startswith("."):
                    proj_name = f[:-3]
                    try:
                        filepath = os.path.join(root, f)
                        with open(filepath, "r", encoding="utf-8") as file_f:
                            content = file_f.read()
                        fm, _ = parse_markdown(content)
                        if fm:
                            cliente_data = fm.get("cliente") or fm.get("clienti")
                            if cliente_data:
                                if isinstance(cliente_data, str):
                                    clients = [cliente_data]
                                elif isinstance(cliente_data, list):
                                    clients = cliente_data
                                else:
                                    clients = []
                                clean_clients = []
                                for c in clients:
                                    if isinstance(c, str):
                                        clean_c = c.replace("[[", "").replace("]]", "").strip()
                                        if clean_c:
                                            clean_clients.append(clean_c)
                                if clean_clients:
                                    project_to_clients[proj_name] = clean_clients
                    except Exception:
                        pass

    if os.path.exists(task_dir):
        for root, _, files in os.walk(task_dir):
            for f in files:
                if f.endswith(".md") and not f.startswith("."):
                    total_tasks += 1
                    try:
                        filepath = os.path.join(root, f)
                        with open(filepath, "r", encoding="utf-8") as file_f:
                            content = file_f.read()
                        fm, _ = parse_markdown(content)
                        if not fm:
                            continue
                            
                        status = fm.get("stato")
                        if status:
                            status_str = str(status).strip()
                            tasks_by_status[status_str] = tasks_by_status.get(status_str, 0) + 1
                            
                        # Determina i clienti per questa task
                        clients = []
                        cliente_data = fm.get("cliente") or fm.get("clienti")
                        if cliente_data:
                            if isinstance(cliente_data, str):
                                clients = [cliente_data]
                            elif isinstance(cliente_data, list):
                                clients = cliente_data
                                
                        clean_clients = []
                        for c in clients:
                            if isinstance(c, str):
                                clean_c = c.replace("[[", "").replace("]]", "").strip()
                                if clean_c:
                                    clean_clients.append(clean_c)
                                    
                        # Se non ci sono clienti diretti, proviamo con il progetto
                        if not clean_clients:
                            progetto_data = fm.get("progetto")
                            if progetto_data:
                                if isinstance(progetto_data, str):
                                    projects = [progetto_data]
                                elif isinstance(progetto_data, list):
                                    projects = progetto_data
                                else:
                                    projects = []
                                for p in projects:
                                    if isinstance(p, str):
                                        clean_p = p.replace("[[", "").replace("]]", "").strip()
                                        if clean_p in project_to_clients:
                                            clean_clients.extend(project_to_clients[clean_p])
                                            
                        seen = set()
                        clean_clients = [x for x in clean_clients if not (x in seen or seen.add(x))]
                        
                        is_completed = (status == "Finito")
                        for clean_c in clean_clients:
                            if is_completed:
                                completed_tasks_by_client[clean_c] = completed_tasks_by_client.get(clean_c, 0) + 1
                    except Exception:
                        pass

    out = ["=== STATISTICHE DEL SECONDO CERVELLO ==="]
    
    if meetings_by_year:
        out.append("\n📅 RIUNIONI PER ANNO:")
        sorted_years = sorted(meetings_by_year.items(), key=lambda x: x[0])
        for yr, count in sorted_years:
            out.append(f"- {yr}: {count} riunioni")
        max_yr, max_count = max(meetings_by_year.items(), key=lambda x: x[1])
        out.append(f"L'anno con più riunioni è il {max_yr} (con {max_count} riunioni).")
    else:
        out.append("\n📅 Nessuna riunione trovata.")
        
    if meetings_by_client:
        out.append("\n🏆 CLASSIFICA CLIENTI CON PIÙ RIUNIONI:")
        sorted_clients = sorted(meetings_by_client.items(), key=lambda x: (-x[1], x[0]))
        for rank, (client, count) in enumerate(sorted_clients, 1):
            out.append(f"{rank}. [[{client}]]: {count} riunioni")
        
    if projects_by_client:
        out.append("\n🏆 CLASSIFICA CLIENTI CON PIÙ PROGETTI:")
        sorted_proj_clients = sorted(projects_by_client.items(), key=lambda x: (-x[1], x[0]))
        for rank, (client, count) in enumerate(sorted_proj_clients, 1):
            out.append(f"{rank}. [[{client}]]: {count} progetti")
            
    if completed_tasks_by_client:
        out.append("\n🏆 CLASSIFICA CLIENTI CON PIÙ TASK SVOLTI:")
        sorted_task_clients = sorted(completed_tasks_by_client.items(), key=lambda x: (-x[1], x[0]))
        for rank, (client, count) in enumerate(sorted_task_clients, 1):
            out.append(f"{rank}. [[{client}]]: {count} task svolti")

    out.append(f"\n✨ PROGETTI (Totale: {total_projects}):")
    out.append(f"- Attivi: {active_projects}")
    out.append(f"- Completati: {completed_projects}")
    
    out.append(f"\n🏢 CLIENTI (Totale: {total_clients}):")
    out.append(f"- Con incarico attivo: {in_essere_clients}")
    
    out.append(f"\n📌 TASK (Totale: {total_tasks}):")
    for st, count in tasks_by_status.items():
        out.append(f"- {st}: {count}")
        
    result = "\n".join(out)
    _stats_cache["time"] = time.time()
    _stats_cache["data"] = result
    return result


def get_detailed_list(type_name: str) -> str:
    """
    Ritorna una lista dettagliata di elementi del tipo specificato (scegliere tra: 'clienti', 'progetti', 'task', 'riunioni').
    Usa questo strumento quando l'utente chiede esplicitamente l'elenco dei progetti, dei clienti, delle riunioni o delle task.
    """
    vault = get_vault_path()
    type_name = type_name.lower().strip()
    
    if "client" in type_name:
        folder = os.path.join(vault, "wiki", "entities", "Clienti")
        title = "ELENCO CLIENTI"
    elif "progett" in type_name:
        folder = os.path.join(vault, "wiki", "entities", "Progetti")
        title = "ELENCO PROGETTI"
    elif "task" in type_name:
        folder = os.path.join(vault, "wiki", "entities", "Task")
        title = "ELENCO TASK"
    elif "riunion" in type_name or "incontro" in type_name:
        folder = os.path.join(vault, "wiki", "sources", "Riunioni")
        title = "ELENCO RIUNIONI"
    else:
        return f"Tipo '{type_name}' non supportato. Scegli tra: 'clienti', 'progetti', 'task', 'riunioni'."
        
    if not os.path.exists(folder):
        return f"Nessun elemento trovato per '{type_name}' (cartella non esistente)."
        
    items = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.endswith(".md") and not f.startswith("."):
                items.append(f[:-3])
                
    if not items:
        return f"Nessun elemento trovato in {title}."
        
    out = [f"=== {title} ==="]
    for item in sorted(items):
        out.append(f"- {item}")
    return "\n".join(out)

def get_agent_instructions(agent_name: str) -> str:
    vault_path = get_vault_path()
    agents_md = os.path.join(vault_path, "agents.md")
    if not os.path.exists(agents_md):
        return ""
    with open(agents_md, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = rf"##\s+{re.escape(agent_name)}\s*\n(.*?)(?=\n##(?![#])|$)"
    match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""

def load_user_profile() -> str:
    vault_path = get_vault_path()
    profile_path = os.path.join(vault_path, "user_profile.md")
    if not os.path.exists(profile_path):
        return ""
    with open(profile_path, "r", encoding="utf-8") as f:
        return f.read()

async def get_query_agent_config() -> LocalAgentConfig:
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    model = settings.get("models", {}).get("query_agent", "gemini-3.5-flash")
    
    identity_inst = get_agent_instructions("Identity (Linee Guida Generali)")
    instructions = get_agent_instructions("Query Agent")
    profile = load_user_profile()
    
    full_system_instructions = f"""
{identity_inst}

---
{instructions}

---
PROFILO UTENTE (WORKING MEMORY):
{profile}
"""
    # Google Auth (Vertex AI / ADC)
    auth = settings.get("google_auth", {})
    kwargs = {}
    if auth.get("use_vertex", False):
        kwargs["vertex"] = True
        if auth.get("project_id"):
            kwargs["project"] = auth["project_id"]
        if auth.get("location"):
            kwargs["location"] = auth["location"]
    from google.antigravity.types import TemplatedSystemInstructions
    templated_si = TemplatedSystemInstructions(
        identity=f"""Sei il "Secondo Cervello" (Second Brain) dell'utente. 
Devi rispondere SEMPRE ED ESCLUSIVAMENTE in lingua ITALIANA.
Non utilizzare MAI l'inglese per rispondere.
Non elencare o esplorare cartelle del filesystem a meno che non ti venga richiesto esplicitamente.

VINCOLO DI SCRITTURA ED AZIONE (CRITICO):
1. Possiedi gli strumenti `create_notion_task` (per creare task/to-do) e `create_wiki_page_tool` (per creare nuove note nel wiki).
2. Non confermare MAI all'utente di aver creato un task o una nota o di aver fatto modifiche a meno che tu non abbia effettivamente eseguito con successo il tool corrispondente.
3. Se l'utente ti chiede di eseguire un'operazione di scrittura o modifica che non è coperta dai tuoi strumenti (es. eliminare file, modificare file arbitrari, ecc.), devi cortesemente spiegare che non hai lo strumento per farlo, anziché far finta di averlo fatto.

COMPORTAMENTO IN CASO DI DATI MANCANTI E PERSONA:
1. Se le ricerche nel vault non producono risultati o sono del tutto irrilevanti per l'entità o la domanda richiesta (es. "Letizia Guglielmi"):
   - Dichiara apertamente e francamente che non sono presenti informazioni a riguardo nel Secondo Cervello.
   - Se possibile, proponi un'ipotesi intellettuale (abduzione) per rispondere, specificando chiaramente che si tratta di un'abduzione e non di una deduzione, con il relativo rischio di speculazione basata su elementi parziali.
   - Sii un'intellettuale colta, raffinata, gramsciana (in connessione sentimentale con il popolo), onesta fino a poter sembrare rude, ma dotata di rigore e precisione.
2. Evita la capitalizzazione in stile inglese (evita le maiuscole automatiche per i sostantivi comuni in italiano).

Le tue istruzioni base sono:
{full_system_instructions}"""
    )

    return LocalAgentConfig(
        model=model,
        system_instructions=templated_si,
        tools=[
            search_vault, 
            read_wiki_page_content, 
            get_second_brain_statistics, 
            get_detailed_list,
            create_notion_task,
            create_wiki_page_tool
        ],
        **kwargs
    )

async def query_agent_with_fallback(question: str, config: LocalAgentConfig, history: list = None) -> str:
    history_context = ""
    if history and not getattr(config, "conversation_id", None):
        history_context = "Cronologia Conversazione (Ultimi messaggi):\n"
        for msg in history:
            role = "Utente" if msg["role"] == "user" else "Assistente"
            history_context += f"{role}: {msg['content']}\n"
        history_context += "\n---\nLa nuova richiesta dell'utente è la seguente:\n"
        
    full_question = history_context + question

    try:
        from engine.utils.llm_fallback import resolve_gemini_key
        gemini_key = resolve_gemini_key(config.model)
        if not gemini_key or gemini_key == "dummy-key":
            raise ValueError("GEMINI_API_KEY non impostata o impostata come dummy-key")
            
        async with Agent(config) as agent:
            response = await agent.chat(full_question)
            resp_text = await response.text()
            if not resp_text or not resp_text.strip():
                raise RuntimeError("Empty response from Agent (likely 429 quota swallowed by SDK)")
            return resp_text
    except Exception as e:
        print(f"[Query Fallback] Gemini API fallita o non disponibile ({e}). Tento RAG locale con LLM di fallback...")
        err_str = str(e).lower()
        if any(x in err_str for x in ["429", "resource_exhausted", "quota", "rate_limit", "rate limit"]):
            try:
                from engine.utils.llm_fallback import save_rate_limited_key
                print(f"[Query Fallback] Rilevato rate limit su Agent primario. Inserisco chiave {gemini_key[:10]}... in blacklist per {config.model}.")
                save_rate_limited_key(gemini_key, config.model)
            except Exception as blacklist_err:
                print(f"[Query Fallback] Errore nel salvataggio della blacklist: {blacklist_err}")
        
        # 2. RAG locale: cerca nel vault ed estrae il contesto tramite ricerca ibrida
        search_results = []
        try:
            search_results = await hybrid_search_vault_func(question, 5)
        except Exception as e:
            print(f"Errore query ricerca ibrida: {e}")
            
        context = ""
        if search_results:
            context = "\n\nRisultati della ricerca nel vault:\n"
            context += "--- FRAMMENTI PIÙ RILEVANTI ---\n"
            for r in search_results:
                context += f"\n--- Nota: {r['path']} ({r['title']}) ---\n{r['snippet']}\n"
                
        # Se la domanda sembra quantitativa o di sintesi, includi i dati statistici deterministici nel contesto
        stats_context = ""
        question_lower = question.lower()
        if any(w in question_lower for w in ["statist", "riunion", "incontr", "progett", "client", "task", "document", "anno", "classific", "quant", "numer", "totale"]):
            try:
                stats_str = await asyncio.to_thread(get_second_brain_statistics)
                stats_context = "\n\n--- Dati Statistici Aggregati Del Secondo Cervello ---\n" + stats_str + "\n"
            except Exception as stats_err:
                print(f"[Query Fallback] Errore nel calcolo delle statistiche per il contesto: {stats_err}")
                
        enriched_prompt = f"{full_question}\n{stats_context}\n{context}"

        sys_inst = config.system_instructions
        sys_inst_text = getattr(sys_inst, "identity", getattr(sys_inst, "text", str(sys_inst)))
        
        # Modifica le system instructions per informare il modello di fallback
        fallback_instructions = f"""
{sys_inst_text}

---
[MODALITÀ FALLBACK - NO STRUMENTI]
In questa modalità non hai accesso diretto agli strumenti (search_wiki, read_wiki_page_content).
Abbiamo già eseguito una ricerca locale per te nel vault Obsidian e abbiamo allegato i risultati pertinenti qui sopra.

REGOLE CRITICHE E PERSONA:
1. Devi rispondere SEMPRE ED ESCLUSIVAMENTE in lingua ITALIANA. Non usare MAI l'inglese per rispondere all'utente.
2. Se il contesto fornito è vuoto, irrilevante o non contiene alcuna informazione reale sull'argomento o sulla persona richiesta (ad esempio, se ti viene chiesto di una persona non presente come "Letizia Guglielmi"):
   - Dichiara onestamente e in modo franco che non ci sono documenti o dati a riguardo all'interno del tuo Secondo Cervello.
   - Formula un'ipotesi speculativa (abduzione) dichiarandola esplicitamente come tale. Spiega che stai facendo un'abduzione e non una deduzione, evidenziando il fattore di rischio intrinseco legato a un'ipotesi costruita su elementi parziali o assenti.
   - Adotta un tono colto, intellettuale, raffinato, ma in "connessione sentimentale" con il popolo (secondo l'insegnamento di Gramsci). Sii diretta, sincera e intellettualmente onesta fino alla rudezza se necessario, ma sempre rispettosa.
3. Evita assolutamente i bias delle AI (evita l'uso delle maiuscole in stile inglese per i sostantivi comuni in italiano).
4. Non inventare dati fingendo che provengano dal vault. Se il contesto è vuoto, dillo chiaramente e procedi con la tua abduzione dichiarata.
"""
        
        from engine.utils.llm_fallback import call_llm_with_fallback
        resp_text = await call_llm_with_fallback(
            prompt=enriched_prompt,
            system_instructions=fallback_instructions,
            gemini_config=config
        )
        
        # Gestione fallback per l'esecuzione manuale dei tool di scrittura
        try:
            import json
            json_block_match = re.search(r'```json\s*(.*?)\s*```', resp_text, re.DOTALL)
            json_str = json_block_match.group(1) if json_block_match else resp_text.strip()
            
            tool_call = json.loads(json_str)
            if isinstance(tool_call, dict) and "action" in tool_call and "action_input" in tool_call:
                action = tool_call["action"]
                action_input = tool_call["action_input"]
                
                if isinstance(action_input, str):
                    try:
                        inputs = json.loads(action_input)
                    except Exception:
                        inputs = {"value": action_input}
                else:
                    inputs = action_input or {}
                    
                print(f"[Fallback Tool Executor] Esecuzione manuale dello strumento '{action}' con input: {inputs}")
                
                if action == "create_notion_task":
                    result = await asyncio.to_thread(
                        create_notion_task,
                        title=inputs.get("title", ""),
                        due_date=inputs.get("due_date"),
                        status=inputs.get("status", "To Do"),
                        category=inputs.get("category", "General")
                    )
                    return result
                elif action == "create_wiki_page_tool":
                    result = await asyncio.to_thread(
                        create_wiki_page_tool,
                        title=inputs.get("title", ""),
                        category=inputs.get("category", ""),
                        content=inputs.get("content", ""),
                        tags=inputs.get("tags")
                    )
                    return result
        except Exception as tool_err:
            # Non è una chiamata a uno strumento o si è verificato un errore di parsing
            pass
            
        return resp_text


async def run_interactive_loop():
    config = await get_query_agent_config()
    print("Inizializzazione sessione interattiva col Secondo Cervello...")
    print("Pronto! Digita 'exit' o 'quit' per uscire.")
    while True:
        try:
            user_input = input("\nUser: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                break
                
            answer = await query_agent_with_fallback(user_input, config)
            print(f"Agent: {answer}")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Errore durante l'interazione: {e}")

async def check_and_respond_chat(agent: Agent, chat_file_path: str):
    if not os.path.exists(chat_file_path):
        return
        
    try:
        with open(chat_file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        lines = content.splitlines()
        # Find the last User: and Agent: indices
        user_idx = -1
        agent_idx = -1
        
        for i, line in enumerate(lines):
            if line.strip().startswith("User:"):
                user_idx = i
            elif line.strip().startswith("Agent:"):
                agent_idx = i
                
        if user_idx > agent_idx:
            # We have a new User query to answer
            query_lines = lines[user_idx:]
            # Reconstruct query text
            query_text = "\n".join(query_lines).replace("User:", "", 1).strip()
            
            if not query_text:
                return
                
            print(f"Nuova richiesta chat rilevata: '{query_text[:40]}...'")
            
            config = await get_query_agent_config()
            resp_text = await query_agent_with_fallback(query_text, config)
            
            # Append response to file
            with open(chat_file_path, "a", encoding="utf-8") as f:
                f.write(f"\n\nAgent: {resp_text}\n")
                
            append_to_log(f"[AI Query] Risposto a chat: '{query_text[:30]}...'")
            print("Risposta scritta in chat.md.")
            
            # Git auto commit
            vault_path = get_vault_path()
            auto_commit(vault_path, f"[AI Query] Risposto a chat: '{query_text[:30]}...'")
            
    except Exception as e:
        print(f"Errore durante la scansione di chat.md: {e}")

async def run_chat_watcher():
    vault_path = get_vault_path()
    chat_file_path = os.path.join(vault_path, "chat.md")
    
    print("Avvio del daemon chat watcher su chat.md...")
    print("Controlli eseguiti ogni 2 secondi. Premi Ctrl+C per arrestare.")
    
    while True:
        try:
            await check_and_respond_chat(None, chat_file_path)
            await asyncio.sleep(2)
        except KeyboardInterrupt:
            print("\nWatcher arrestato.")
            break
        except Exception as e:
            print(f"Errore watcher: {e}")
            await asyncio.sleep(5)

async def run_single_query(question: str):
    config = await get_query_agent_config()
    answer = await query_agent_with_fallback(question, config)
    print(f"Agent: {answer}")

async def query_agent_answer(question: str, history: list = None, conversation_id: str = None) -> str:
    config = await get_query_agent_config()
    if conversation_id:
        config.conversation_id = conversation_id
    return await query_agent_with_fallback(question, config, history=history)

async def query_agent_stream(question: str, history: list = None, conversation_id: str = None):
    config = await get_query_agent_config()
    if conversation_id:
        config.conversation_id = conversation_id
        
    history_context = ""
    if history and not conversation_id:
        history_context = "Cronologia Conversazione (Ultimi messaggi):\n"
        for msg in history:
            role = "Utente" if msg["role"] == "user" else "Assistente"
            history_context += f"{role}: {msg['content']}\n"
        history_context += "\n---\nLa nuova richiesta dell'utente è la seguente:\n"
        
    full_question = history_context + question

    try:
        from engine.utils.llm_fallback import resolve_gemini_key
        gemini_key = resolve_gemini_key(config.model)
        if not gemini_key or gemini_key == "dummy-key":
            raise ValueError("GEMINI_API_KEY non impostata o impostata come dummy-key")
            
        async with Agent(config) as agent:
            response = await agent.chat(full_question)
            async for token in response:
                yield token
    except Exception as e:
        print(f"[Query Streaming] Agent primario fallito ({e}). Tento fallback...")
        err_str = str(e).lower()
        if any(x in err_str for x in ["429", "resource_exhausted", "quota", "rate_limit", "rate limit"]):
            try:
                from engine.utils.llm_fallback import save_rate_limited_key
                save_rate_limited_key(gemini_key, config.model)
            except Exception:
                pass
                
        fallback_res = await query_agent_with_fallback(question, config, history=history)
        yield fallback_res

if __name__ == "__main__":
    # Interactive default
    asyncio.run(run_interactive_loop())
