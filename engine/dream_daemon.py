import os
import re
import asyncio
import datetime
from dotenv import load_dotenv

from engine.utils.markdown import load_settings, parse_markdown, to_markdown
from engine.utils.llm_fallback import call_llm_with_fallback
from engine.tools.vault_tools import get_vault_path, write_wiki_page, append_to_log
from google.antigravity import LocalAgentConfig

def get_vault_nodes(vault_path: str) -> list[dict]:
    nodes = []
    
    scan_dirs = [
        ("concept", os.path.join(vault_path, "wiki", "concepts")),
        ("entity", os.path.join(vault_path, "wiki", "entities"))
    ]
    
    for node_type, folder in scan_dirs:
        if not os.path.exists(folder):
            continue
        for root, _, files in os.walk(folder):
            for file in files:
                if file.endswith(".md") and not file.startswith("."):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            content = f.read()
                        fm, body = parse_markdown(content)
                        clean_body = body.strip()
                        snippet = clean_body[:300] + "..." if len(clean_body) > 300 else clean_body
                        nodes.append({
                            "type": node_type,
                            "title": file.replace(".md", ""),
                            "path": os.path.relpath(filepath, vault_path),
                            "snippet": snippet,
                            "related": fm.get("related", [])
                        })
                    except Exception:
                        pass
    return nodes

async def run_dream_mode():
    load_dotenv()
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    
    print("Avvio Modalità Sogno notturna (Dream Mode)...")
    
    # 1. Raccogli tutti i nodi (concetti ed entità)
    nodes = get_vault_nodes(vault_path)
    if not nodes:
        print("Nessun nodo trovato nel vault per elaborare il sogno.")
        return
        
    print(f"Rilevati {len(nodes)} nodi semantici nel Secondo Cervello.")
    
    # Costruisci un sommario compatto per l'LLM
    nodes_summary = ""
    for n in nodes[:150]:  # Limita a 150 nodi per rimanere nei limiti di contesto
        nodes_summary += f"- [[{n['title']}]]: {n['snippet']}\n"
        if n['related']:
            nodes_summary += f"  (Relazioni: {', '.join(n['related'])})\n"
            
    system_instructions = """
    Sei il 'Reflect Agent' in modalità notturna ("sogno"). Il tuo scopo è rielaborare le informazioni del Secondo Cervello in autonomia.
    Analizza i concetti e le entità fornite. Cerca di:
    1. Trovare connessioni invisibili: relazioni non esplicite tra concetti distanti (es. come un progetto si collega a un concetto teorico).
    2. Rilevare anomalie o contraddizioni logiche tra le note.
    3. Identificare possibili gerarchie padre-figlio.
    Scrivi una nota di sintesi profonda, acuta, evocativa ma pragmatica, intitolata 'Sogno del [Data odierna]'. Usa wikilink Obsidian nel testo.
    """
    
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    prompt = f"""
    Ecco l'estratto dei nodi attuali del Secondo Cervello:
    ---
    {nodes_summary}
    ---
    
    Elabora il Sogno per la data {today_str}.
    Genera un report strutturato in capitoli:
    ## 1. Connessioni Latenti Rilevate
    Descrivi quali concetti o entità dovrebbero essere collegati tra loro e perché (indicando i wikilink).
    
    ## 2. Anomalie o Conflitti Informativi
    Se ci sono note che si contraddicono o informazioni frammentate, evidenziale.
    
    ## 3. Evoluzione Proposta
    Suggerisci nuove note concetto o strutture gerarchiche per ottimizzare il vault.
    
    Rispondi solo con il markdown del report.
    """
    
    # Configura l'agente
    model = settings.get("models", {}).get("reflect_agent", "gemini-3.5-flash")
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
        system_instructions="Sei un agente che analizza grafi semantici in modalità notturna.",
        **kwargs
    )
    
    try:
        dream_content = await call_llm_with_fallback(prompt, system_instructions, config)
    except Exception as e:
        print(f"Errore durante la generazione del sogno LLM: {e}")
        return
        
    # Scrivi la nota di sintesi nel vault
    dream_filename = f"wiki/synthesis/dream_{today_str}.md"
    fm = {
        "type": "dream_synthesis",
        "date": today_str
    }
    
    write_wiki_page(dream_filename, dream_content, fm)
    append_to_log(f"[Dream Mode] Generata sintesi notturna in [[{dream_filename}]]")
    
    # Auto commit se abilitato
    if settings.get("preferences", {}).get("auto_commit", True):
        from engine.git_ops import auto_commit
        auto_commit(vault_path, f"[AI Dream] Generata sintesi notturna {today_str}")
        
    print(f"Sogno notturno completato e salvato in {dream_filename}.")

if __name__ == "__main__":
    asyncio.run(run_dream_mode())
