import os
import asyncio
from watchfiles import awatch
from engine.tools.vault_tools import get_vault_path

async def watch_vault_changes(ingestion_manager):
    vault_path = get_vault_path()
    raw_dir = os.path.join(vault_path, "raw")
    meetings_dir = os.path.join(vault_path, "Meetings")
    
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(meetings_dir, exist_ok=True)
    
    print(f"[WATCHER] Monitoraggio avviato su: {raw_dir} e {meetings_dir}", flush=True)
    
    debounce_task = None
    
    async def trigger_ingestion_after_delay(delay: float):
        await asyncio.sleep(delay)
        if not ingestion_manager.is_running():
            print("[WATCHER] Avvio dell'ingestione automatica in background...", flush=True)
            await ingestion_manager.start()
        else:
            print("[WATCHER] Ingestione già in esecuzione, salto il trigger.", flush=True)

    try:
        async for changes in awatch(raw_dir, meetings_dir):
            relevant = False
            for change_type, path in changes:
                rel_path = os.path.relpath(path, vault_path)
                
                # Salta file temporanei, cartella allegati mail e file nascosti
                if "mail_attachments" in rel_path or "/." in rel_path or "\\." in rel_path or rel_path.endswith(".gitkeep"):
                    continue
                    
                _, ext = os.path.splitext(rel_path.lower())
                if ext in [".md", ".txt", ".json", ".csv", ".xlsx", ".xls", ".docx", ".doc"]:
                    relevant = True
                    break
            
            if relevant:
                print("[WATCHER] Rilevate modifiche ai file. Ingestione programmata tra 3 secondi...", flush=True)
                if debounce_task and not debounce_task.done():
                    debounce_task.cancel()
                debounce_task = asyncio.create_task(trigger_ingestion_after_delay(3.0))
    except asyncio.CancelledError:
        print("[WATCHER] Watcher cancellato.", flush=True)
        if debounce_task and not debounce_task.done():
            debounce_task.cancel()
    except Exception as e:
        print(f"[WATCHER] Errore imprevisto nel watcher: {e}", flush=True)
