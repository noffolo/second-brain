import os
import datetime
from dotenv import load_dotenv
from engine.utils.markdown import load_settings, parse_markdown, to_markdown
from engine.tools.notion_tools import query_notion_database
import re


try:
    from notion_client import Client
    NOTION_CLIENT_AVAILABLE = True
except ImportError:
    NOTION_CLIENT_AVAILABLE = False

def get_vault_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def parse_notion_date_only(date_prop: dict) -> str:
    if not date_prop or date_prop.get("type") != "date" or not date_prop.get("date"):
        return ""
    date_data = date_prop["date"]
    start_str = date_data.get("start", "")
    if "T" in start_str:
        return start_str.split("T")[0]
    return start_str

def get_notion_status_value(prop: dict) -> str:
    if not prop:
        return ""
    p_type = prop.get("type")
    if p_type == "status":
        status_data = prop.get("status")
        return status_data.get("name", "") if status_data else ""
    elif p_type == "select":
        select_data = prop.get("select")
        return select_data.get("name", "") if select_data else ""
    elif p_type == "checkbox":
        return "Done" if prop.get("checkbox", False) else "To Do"
    return ""

def set_notion_status_value(client, page_id: str, prop_name: str, prop_type: str, status_val: str):
    properties = {}
    if prop_type == "status":
        properties[prop_name] = {"status": {"name": status_val}}
    elif prop_type == "select":
        properties[prop_name] = {"select": {"name": status_val}}
    elif prop_type == "checkbox":
        properties[prop_name] = {"checkbox": status_val.lower() in ["done", "completato", "true"]}
    
    if properties:
        client.pages.update(page_id=page_id, properties=properties)

def find_local_task_files(vault_path: str) -> dict[str, str]:
    """
    Trova tutti i file di task locali (.md) che contengono 'notion_page_id' nel frontmatter.
    Ritorna un dizionario {notion_page_id: rel_path}.
    """
    local_tasks = {}
    entities_dir = os.path.join(vault_path, "wiki", "entities")
    if not os.path.exists(entities_dir):
        return local_tasks
        
    for root, _, files in os.walk(entities_dir):
        for file in files:
            if file.endswith(".md") and not file.startswith("."):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    fm, _ = parse_markdown(content)
                    if fm.get("type") in ["microtheme", "task"] and fm.get("notion_page_id"):
                        local_tasks[fm["notion_page_id"]] = os.path.relpath(filepath, vault_path)
                except Exception:
                    pass
    return local_tasks

def notion_tasks_sync() -> int:
    load_dotenv()
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    
    notion_settings = settings.get("sources", {}).get("notion", {})
    if not notion_settings.get("enabled", False):
        print("Sorgente Notion disabilitata nelle impostazioni.")
        return 0
        
    token = os.getenv("NOTION_TOKEN")
    if not token:
        print("Errore: NOTION_TOKEN non impostato nel file .env per notion_tasks_sync.")
        return 0
        
    db_id = notion_settings.get("tasks_database_id", "")
    if not db_id:
        print("Notion tasks_database_id non impostato in settings.md.")
        return 0
        
    if not NOTION_CLIENT_AVAILABLE:
        print("Libreria 'notion-client' non installata. Salto sincronizzazione Notion Tasks.")
        return 0
        
    tasks_processed = 0
    try:
        client = Client(auth=token)
        local_tasks = find_local_task_files(vault_path)
        
        print(f"Interrogazione database Notion Tasks: {db_id}...")
        results = []
        has_more = True
        next_cursor = None
        
        while has_more:
            body = {}
            if next_cursor:
                body["start_cursor"] = next_cursor
            resp = query_notion_database(client, db_id, body)
            results.extend(resp.get("results", []))
            has_more = resp.get("has_more", False)
            next_cursor = resp.get("next_cursor")
            
        print(f"Trovati {len(results)} task in Notion Tasks.")
        
        for page in results:
            page_id = page["id"]
            title = "Task senza titolo"
            status_val = "To Do"
            due_date = ""
            
            properties = page.get("properties", {})
            status_prop_name = ""
            status_prop_type = ""
            
            # Extract title
            for prop_name, prop_data in properties.items():
                if prop_data.get("type") == "title":
                    title_list = prop_data.get("title", [])
                    if title_list:
                        title = "".join([t.get("plain_text", "") for t in title_list])
                        break
            
            # Find status property and extract status value
            for prop_name, prop_data in properties.items():
                p_type = prop_data.get("type")
                if p_type in ["status", "select", "checkbox"]:
                    status_prop_name = prop_name
                    status_prop_type = p_type
                    status_val = get_notion_status_value(prop_data) or "To Do"
                    break
                    
            # Extract due date
            for prop_name, prop_data in properties.items():
                if prop_data.get("type") == "date" and prop_name.lower() in ["due date", "scadenza", "data"]:
                    due_date = parse_notion_date_only(prop_data)
                    break
            
            # remote epoch
            last_edited_str = page.get("last_edited_time", "")
            remote_epoch = 0
            if last_edited_str:
                try:
                    remote_time = datetime.datetime.fromisoformat(last_edited_str.replace("Z", "+00:00"))
                    remote_epoch = remote_time.timestamp()
                except Exception:
                    pass
            
            local_rel_path = local_tasks.get(page_id)
            local_changed = False
            local_status = ""
            local_mtime = 0
            
            if local_rel_path:
                local_abs_path = os.path.join(vault_path, local_rel_path)
                if os.path.exists(local_abs_path):
                    local_mtime = os.path.getmtime(local_abs_path)
                    try:
                        with open(local_abs_path, "r", encoding="utf-8") as f:
                            l_content = f.read()
                        l_fm, _ = parse_markdown(l_content)
                        local_status = l_fm.get("status", "")
                        if local_status and local_status != status_val:
                            # Status mismatch! Check which is newer
                            if local_mtime > remote_epoch:
                                local_changed = True
                    except Exception:
                        pass
            
            if local_changed and status_prop_name:
                # Local change is newer: update Notion!
                print(f"Aggiornamento status Notion per '{title}' -> '{local_status}'...")
                try:
                    set_notion_status_value(client, page_id, status_prop_name, status_prop_type, local_status)
                    # Sincronizza il timestamp locale per evitare loop di modifiche
                    os.utime(os.path.join(vault_path, local_rel_path), None)
                except Exception as e:
                    print(f"Errore durante l'aggiornamento status su Notion: {e}")
            else:
                # Notion is newer or equal: update local!
                clean_title = re.sub(r'[\\/*?:"<>|]', "", title)
                if not local_rel_path:
                    # Determina la categoria di default
                    category = os.getenv("NOTION_TASK_DEFAULT_CATEGORY")
                    if not category:
                        # Scansiona wiki/entities alla ricerca di cartelle personalizzate non-generiche
                        entities_dir = os.path.join(vault_path, "wiki", "entities")
                        if os.path.exists(entities_dir):
                            try:
                                subdirs = [d for d in os.listdir(entities_dir) if os.path.isdir(os.path.join(entities_dir, d)) and not d.startswith('.')]
                                custom_subdirs = [d for d in subdirs if d not in ["General", "AI_LLM_Coding", "Design_Branding"]]
                                if custom_subdirs:
                                    category = custom_subdirs[0]
                            except Exception:
                                pass
                    if not category:
                        category = "General"
                        
                    local_rel_path = f"wiki/entities/{category}/{clean_title}.md"
                
                local_abs_path = os.path.join(vault_path, local_rel_path)
                os.makedirs(os.path.dirname(local_abs_path), exist_ok=True)
                
                # Format body and frontmatter
                fm = {
                    "type": "microtheme",
                    "title": title,
                    "status": status_val,
                    "due_date": due_date or None,
                    "source": "notion",
                    "notion_page_id": page_id
                }
                
                body = f"# {title}\n\n"
                body += f"**Stato**: {status_val}\n"
                if due_date:
                    body += f"**Scadenza**: {due_date}\n"
                    
                full_md = to_markdown(fm, body)
                
                # Write file only if changed
                need_write = True
                if os.path.exists(local_abs_path):
                    with open(local_abs_path, "r", encoding="utf-8") as f:
                        if f.read().strip() == full_md.strip():
                            need_write = False
                            
                if need_write:
                    print(f"Download/Aggiornamento locale task: '{title}' ({status_val})")
                    with open(local_abs_path, "w", encoding="utf-8") as f:
                        f.write(full_md)
                    # Imposta l'orario di modifica del file locale all'orario di modifica remoto
                    os.utime(local_abs_path, (remote_epoch, remote_epoch))
                    
            tasks_processed += 1
            
        return tasks_processed
        
    except Exception as e:
        print(f"Errore durante sincronizzazione Notion Tasks: {e}")
        return tasks_processed

if __name__ == "__main__":
    notion_tasks_sync()
