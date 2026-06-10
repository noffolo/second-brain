import os
import re
import time
import asyncio
from google.antigravity import Agent, LocalAgentConfig
from engine.utils.markdown import load_settings
from engine.tools.vault_tools import get_vault_path, search_wiki, append_to_log
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

def get_second_brain_statistics() -> str:
    """
    Ritorna statistiche aggregate del Secondo Cervello, come il numero di riunioni per anno,
    il numero totale di progetti (completati e attivi), il numero di clienti, task e documenti.
    Usa questo strumento per rispondere a domande quantitative, aggregazioni, conteggi o riassuntive sui dati strutturati (es. riunioni per anno, progetti attivi, clienti).
    """
    vault = get_vault_path()
    
    # 1. Riunioni per anno
    meetings_by_year = {}
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
                        with open(os.path.join(root, f), "r", encoding="utf-8") as file_f:
                            content = file_f.read(800)
                        match_start = re.search(r"start_time:\s*['\"]?(\d{4})", content)
                        match_quando = re.search(r"Quando\?:\s*['\"]?(\d{4})", content)
                        year = None
                        if match_start:
                            year = match_start.group(1)
                        elif match_quando:
                            year = match_quando.group(1)
                        if year:
                            meetings_by_year[year] = meetings_by_year.get(year, 0) + 1
                    except Exception:
                        pass
                        
    # 2. Progetti
    projects_dir = os.path.join(vault, "wiki", "entities", "Progetti")
    total_projects = 0
    active_projects = 0
    completed_projects = 0
    if os.path.exists(projects_dir):
        for root, _, files in os.walk(projects_dir):
            for f in files:
                if f.endswith(".md") and not f.startswith("."):
                    total_projects += 1
                    try:
                        with open(os.path.join(root, f), "r", encoding="utf-8") as file_f:
                            content = file_f.read(800)
                        if "completato?: true" in content.lower():
                            completed_projects += 1
                        else:
                            active_projects += 1
                    except Exception:
                        active_projects += 1

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
    if os.path.exists(task_dir):
        for root, _, files in os.walk(task_dir):
            for f in files:
                if f.endswith(".md") and not f.startswith("."):
                    total_tasks += 1
                    try:
                        with open(os.path.join(root, f), "r", encoding="utf-8") as file_f:
                            content = file_f.read(800)
                        status_match = re.search(r"stato:\s*['\"]?([^'\n\"]+)", content.lower())
                        if status_match:
                            status = status_match.group(1).strip()
                            tasks_by_status[status] = tasks_by_status.get(status, 0) + 1
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
        
    out.append(f"\n✨ PROGETTI (Totale: {total_projects}):")
    out.append(f"- Attivi: {active_projects}")
    out.append(f"- Completati: {completed_projects}")
    
    out.append(f"\n🏢 CLIENTI (Totale: {total_clients}):")
    out.append(f"- Con incarico attivo: {in_essere_clients}")
    
    out.append(f"\n📌 TASK (Totale: {total_tasks}):")
    for st, count in tasks_by_status.items():
        out.append(f"- {st}: {count}")
        
    return "\n".join(out)

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
    pattern = rf"##\s+{agent_name}\s*\n(.*?)(?=\n##(?![#])|$)"
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
    
    instructions = get_agent_instructions("Query Agent")
    profile = load_user_profile()
    
    full_system_instructions = f"""
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

    return LocalAgentConfig(
        model=model,
        system_instructions=full_system_instructions,
        tools=[search_wiki, read_wiki_page_content, get_second_brain_statistics, get_detailed_list],
        **kwargs
    )

async def query_agent_with_fallback(question: str, config: LocalAgentConfig) -> str:
    # 1. Prova ad usare l'Agent nativo di Gemini (con tool search_wiki/read_wiki_page_content)
    try:
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if not gemini_key or gemini_key == "dummy-key":
            raise ValueError("GEMINI_API_KEY non impostata o impostata come dummy-key")
            
        async with Agent(config) as agent:
            response = await agent.chat(question)
            return await response.text()
    except Exception as e:
        print(f"[Query Fallback] Gemini API fallita o non disponibile ({e}). Tento RAG locale con LLM di fallback...")
        
        # 2. RAG locale: cerca nel vault ed estrae il contesto
        search_results = search_wiki(question)
        if not search_results:
            # Fallback a ricerca per parole chiave con stemming italiano rudimentale
            words = re.sub(r'[^\w\s\’\']', ' ', question.lower()).split()
            stopwords = {
                "l'anno", "anno", "anni", "abbiamo", "fatto", "facciamo", "fare", "più", "classifica", "clienti", "cliente",
                "in", "con", "cui", "e", "il", "la", "i", "gli", "le", "di", "da", "per", "su", "a", "del", "dei", "degli",
                "assoluto", "assoluto", "quello", "quelli", "quella", "questo", "questi", "questa", "sono", "stato", "stati", "era", "erano"
            }
            keywords = []
            for w in words:
                w_clean = w.strip("’'")
                if len(w_clean) >= 4 and w_clean not in stopwords:
                    stem = w_clean
                    if w_clean[-1] in 'oaiei' and len(w_clean) > 4:
                        stem = w_clean[:-1]
                    if stem not in keywords:
                        keywords.append(stem)
            
            seen_paths = set()
            search_results = []
            for kw in keywords[:3]:  # primi 3 stem più significativi
                kw_results = search_wiki(kw)
                for r in kw_results:
                    if r['path'] not in seen_paths:
                        seen_paths.add(r['path'])
                        search_results.append(r)
        
        context = ""
        if search_results:
            context = "\n\nRisultati della ricerca nel vault:\n"
            context += "--- CONTENUTI DELLE NOTE PIÙ RILEVANTI ---\n"
            for r in search_results[:10]: # primi 10 file completi
                page_content = read_wiki_page_content(r['path'])
                context += f"\n--- Nota: {r['path']} ---\n{page_content}\n"
                
            if len(search_results) > 10:
                context += "\n--- ALTRE NOTE RILEVANTI TROVATE NEL VAULT (SOLO PERCORSI) ---\n"
                for r in search_results[10:30]: # altri 20 percorsi per dare visibilità globale
                    context += f"- {r['path']} (Titolo: {r['title']})\n"
                
        enriched_prompt = f"{question}\n{context}"
        
        # Modifica le system instructions per informare il modello di fallback
        fallback_instructions = f"""
{config.system_instructions}

---
[MODALITÀ FALLBACK - NO STRUMENTI]
In questa modalità non hai accesso diretto agli strumenti (search_wiki, read_wiki_page_content).
Abbiamo già eseguito una ricerca locale per te nel vault Obsidian e abbiamo allegato i risultati pertinenti qui sopra.
Usa esclusivamente il contesto fornito per rispondere alla domanda dell'utente. Non cercare di invocare funzioni o righe di comando, e rispondi direttamente e in modo naturale all'utente in italiano.
"""
        
        from engine.utils.llm_fallback import call_llm_with_fallback
        return await call_llm_with_fallback(
            prompt=enriched_prompt,
            system_instructions=fallback_instructions,
            gemini_config=config
        )

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

async def query_agent_answer(question: str) -> str:
    config = await get_query_agent_config()
    return await query_agent_with_fallback(question, config)

if __name__ == "__main__":
    # Interactive default
    asyncio.run(run_interactive_loop())
