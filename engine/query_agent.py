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
        tools=[search_wiki, read_wiki_page_content],
        **kwargs
    )

async def run_interactive_loop():
    config = await get_query_agent_config()
    print("Inizializzazione sessione interattiva col Secondo Cervello...")
    async with Agent(config) as agent:
        print("Pronto! Digita 'exit' o 'quit' per uscire.")
        while True:
            try:
                user_input = input("\nUser: ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ["exit", "quit"]:
                    break
                    
                response = await agent.chat(user_input)
                print("Agent: ", end="")
                async for chunk in response:
                    print(chunk, end="", flush=True)
                print()
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
            
            # Send message to agent
            response = await agent.chat(query_text)
            resp_text = await response.text()
            
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
    
    config = await get_query_agent_config()
    print("Avvio del daemon chat watcher su chat.md...")
    print("Controlli eseguiti ogni 2 secondi. Premi Ctrl+C per arrestare.")
    
    async with Agent(config) as agent:
        while True:
            try:
                await check_and_respond_chat(agent, chat_file_path)
                await asyncio.sleep(2)
            except KeyboardInterrupt:
                print("\nWatcher arrestato.")
                break
            except Exception as e:
                print(f"Errore watcher: {e}")
                await asyncio.sleep(5)

async def run_single_query(question: str):
    config = await get_query_agent_config()
    async with Agent(config) as agent:
        response = await agent.chat(question)
        print("Agent: ", end="")
        async for chunk in response:
            print(chunk, end="", flush=True)
        print()

async def query_agent_answer(question: str) -> str:
    config = await get_query_agent_config()
    async with Agent(config) as agent:
        response = await agent.chat(question)
        return await response.text()

if __name__ == "__main__":
    # Interactive default
    asyncio.run(run_interactive_loop())
