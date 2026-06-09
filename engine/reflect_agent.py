import os
import re
import time
import datetime
import asyncio
from google.antigravity import Agent, LocalAgentConfig
from engine.utils.markdown import load_settings, parse_markdown
from engine.tools.vault_tools import (
    get_vault_path,
    write_wiki_page,
    append_to_log,
    update_index
)
from engine.git_ops import auto_commit

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

def get_recent_files(directory_path: str, max_files: int = 5, max_days: int = 7) -> list[tuple[str, str]]:
    """
    Returns a list of tuples (filename, content) of recent markdown files.
    Filters by modification time within max_days, falling back to the max_files most recent if empty.
    """
    if not os.path.exists(directory_path):
        return []
        
    md_files = []
    for f in os.listdir(directory_path):
        if f.endswith(".md") and not f.startswith("."):
            full_path = os.path.join(directory_path, f)
            mtime = os.path.getmtime(full_path)
            md_files.append((f, full_path, mtime))
            
    if not md_files:
        return []
        
    # Sort by mtime descending (newest first)
    md_files.sort(key=lambda x: x[2], reverse=True)
    
    now = time.time()
    recent = []
    
    # Filter by age
    for name, path, mtime in md_files:
        age_days = (now - mtime) / (24 * 3600)
        if age_days <= max_days:
            try:
                with open(path, "r", encoding="utf-8") as file_f:
                    recent.append((name, file_f.read()))
            except Exception:
                pass
                
    # Fallback to last N files if nothing in the last week
    if not recent:
        for name, path, mtime in md_files[:max_files]:
            try:
                with open(path, "r", encoding="utf-8") as file_f:
                    recent.append((name, file_f.read()))
            except Exception:
                pass
                
    return recent

async def run_reflection():
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    model = settings.get("models", {}).get("reflect_agent", "gemini-3.5-flash")
    
    instructions = get_agent_instructions("Reflect Agent")
    
    # Get inputs
    journals = get_recent_files(os.path.join(vault_path, "journal"), max_files=5, max_days=7)
    meetings = get_recent_files(os.path.join(vault_path, "Meetings"), max_files=5, max_days=7)
    sources = get_recent_files(os.path.join(vault_path, "wiki", "sources"), max_files=5, max_days=7)
    
    # Check if we have anything to reflect on
    if not journals and not meetings and not sources:
        print("Nessun contenuto recente (diari, riunioni, sorgenti) trovato per la riflessione.")
        return
        
    # Prepare prompt context
    context_parts = []
    
    if journals:
        context_parts.append("### DIARI RECENTI:")
        for name, content in journals:
            context_parts.append(f"File: journal/{name}\n---\n{content}\n---")
            
    if meetings:
        context_parts.append("### VERBALI DI RIUNIONE RECENTI:")
        for name, content in meetings:
            context_parts.append(f"File: Meetings/{name}\n---\n{content}\n---")
            
    if sources:
        context_parts.append("### FONTI RECENTI:")
        for name, content in sources:
            context_parts.append(f"File: wiki/sources/{name}\n---\n{content}\n---")
            
    context_text = "\n\n".join(context_parts)
    
    # YYYY-WNN
    today = datetime.date.today()
    year, week, _ = today.isocalendar()
    reflection_filename = f"{year}-W{week:02d}_reflection.md"
    reflection_rel_path = f"wiki/synthesis/{reflection_filename}"
    
    prompt = f"""
Genera la riflessione settimanale per la settimana {week} dell'anno {year}.
Di seguito trovi i diari, i verbali delle riunioni e le fonti dell'ultima settimana:

{context_text}

---
Rivedi questi dati per:
1. Identificare pattern emergenti (temi ricorrenti).
2. Scoprire connessioni invisibili tra le fonti teoriche, i meeting e le riflessioni del diario.
3. Suggerire focus futuri ed evoluzione dei progetti.
4. Suggerire eventuali contatti del CRM da ricontattare in base alle discussioni avvenute.

Genera una pagina markdown strutturata con:
- Un titolo principale: # Riflessione Settimanale YYYY-WNN
- Una sezione ## Pattern Emergenti
- Una sezione ## Connessioni Invisibili
- Una sezione ## Azioni e Prossimi Passi
- Una sezione ## Suggerimenti per il Profilo Utente

Usa abbondantemente wikilink `[[Nome Pagina]]` per connettere la riflessione a concetti, entità o sorgenti esistenti nel vault.
Restituisci solo ed esclusivamente il markdown della pagina.
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
            
    config = LocalAgentConfig(
        model=model,
        system_instructions=instructions,
        **kwargs
    )
    print(f"Avvio Reflect Agent con modello '{model}' per generare {reflection_filename}...")
    async with Agent(config) as agent:
        try:
            response = await agent.chat(prompt)
            resp_text = await response.text()
            
            # Save reflection
            fm = {
                "type": "synthesis",
                "week": f"{year}-W{week:02d}",
                "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            write_wiki_page(reflection_rel_path, resp_text, fm)
            update_index(reflection_rel_path, f"Riflessione settimanale della settimana W{week}")
            append_to_log(f"[AI Reflect] Generata riflessione settimanale [[{reflection_filename.replace('.md', '')}]]")
            
            # Git auto commit
            auto_commit(vault_path, f"[AI Reflect] Generata riflessione settimanale W{week}")
            print(f"Riflessione settimanale generata con successo: {reflection_rel_path}")
            
        except Exception as e:
            print(f"Errore durante la generazione della riflessione: {e}")

if __name__ == "__main__":
    asyncio.run(run_reflection())
