import os
import re
import datetime
from dotenv import load_dotenv
from engine.utils.markdown import load_settings, to_markdown
from engine.tools.notion_tools import query_notion_database


try:
    from notion_client import Client
    NOTION_CLIENT_AVAILABLE = True
except ImportError:
    NOTION_CLIENT_AVAILABLE = False

def get_vault_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def parse_notion_date(date_prop: dict) -> tuple[str, str]:
    if not date_prop or date_prop.get("type") != "date" or not date_prop.get("date"):
        return "", ""
    
    date_data = date_prop["date"]
    start_str = date_data.get("start", "")
    end_str = date_data.get("end", "") or ""
    
    # Format dates
    def format_iso(iso_str):
        if not iso_str:
            return ""
        try:
            # Check if has time
            if "T" in iso_str:
                dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                dt = datetime.datetime.strptime(iso_str, "%Y-%m-%d")
                return dt.strftime("%Y-%m-%d")
        except Exception:
            return iso_str
            
    return format_iso(start_str), format_iso(end_str)

def get_notion_text_prop(prop: dict) -> str:
    if not prop:
        return ""
    p_type = prop.get("type")
    if p_type == "rich_text":
        text_list = prop.get("rich_text", [])
        return "".join([t.get("plain_text", "") for t in text_list])
    elif p_type == "select":
        select_data = prop.get("select")
        return select_data.get("name", "") if select_data else ""
    return ""

def notion_calendar_sync() -> int:
    load_dotenv()
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    
    notion_settings = settings.get("sources", {}).get("notion", {})
    if not notion_settings.get("enabled", False):
        print("Sorgente Notion disabilitata nelle impostazioni.")
        return 0
        
    token = os.getenv("NOTION_TOKEN")
    if not token:
        print("Errore: NOTION_TOKEN non impostato nel file .env per notion_calendar_sync.")
        return 0
        
    db_id = notion_settings.get("calendar_database_id", "")
    if not db_id:
        print("Notion calendar_database_id non impostato in settings.md.")
        return 0
        
    if not NOTION_CLIENT_AVAILABLE:
        print("Libreria 'notion-client' non installata. Salto sincronizzazione Notion Calendar.")
        return 0
        
    events_synced = 0
    try:
        client = Client(auth=token)
        dest_dir = os.path.join(vault_path, "wiki", "sources", "Riunioni")
        os.makedirs(dest_dir, exist_ok=True)
        
        print(f"Interrogazione database Notion Calendar: {db_id}...")
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
            
        print(f"Trovati {len(results)} eventi in Notion Calendar.")
        
        for page in results:
            page_id = page["id"]
            title = "Evento senza titolo"
            start_time, end_time = "", ""
            location = ""
            
            properties = page.get("properties", {})
            
            # Extract title
            for prop_name, prop_data in properties.items():
                if prop_data.get("type") == "title":
                    title_list = prop_data.get("title", [])
                    if title_list:
                        title = "".join([t.get("plain_text", "") for t in title_list])
                        break
                        
            # Extract date
            for prop_name, prop_data in properties.items():
                if prop_data.get("type") == "date":
                    start_time, end_time = parse_notion_date(prop_data)
                    break
                    
            # Extract location (heuristic: name is Location, Luogo, o select type)
            for prop_name, prop_data in properties.items():
                if prop_name.lower() in ["location", "luogo", "posto"]:
                    location = get_notion_text_prop(prop_data)
                    break
            
            if not start_time:
                # Se non ha una data, salta
                continue
                
            import re
            clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
            if not clean_title:
                clean_title = f"Evento_{page_id.replace('-', '')}"
            filename = f"{clean_title}.md"
            filepath = os.path.join(dest_dir, filename)
            
            # Format frontmatter
            quando = start_time[:10] if start_time else ""
            fm = {
                "type": "meeting",
                "title": title,
                "quando": quando,
                "start_time": start_time,
                "end_time": end_time or None,
                "location": location or None,
                "source": "notion",
                "notion_page_id": page_id
            }
            
            body = f"# {title}\n\n"
            body += f"**Inizio**: {start_time}\n"
            if end_time:
                body += f"**Fine**: {end_time}\n"
            if location:
                body += f"**Luogo**: {location}\n"
                
            full_md = to_markdown(fm, body)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(full_md)
                
            # Indicizzazione in tempo reale in ChromaDB
            try:
                from engine.utils.vector_db import get_vector_db
                from engine.tools.embedder import chunk_text
                db = get_vector_db()
                rel_path = os.path.relpath(filepath, vault_path)
                db.upsert_chunks(rel_path, title, chunk_text(body))
            except Exception as e:
                print(f"Errore indicizzazione vettoriale per {filepath}: {e}")
                
            events_synced += 1
            
        return events_synced
        
    except Exception as e:
        print(f"Errore durante sincronizzazione Notion Calendar: {e}")
        return events_synced

def create_notion_calendar_event(title: str, start_time: str, end_time: str = None, location: str = None) -> str:
    """
    Crea un nuovo evento (riunione) sia su Notion che nel vault locale Obsidian in wiki/sources/Riunioni/.
    """
    load_dotenv()
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    
    notion_settings = settings.get("sources", {}).get("notion", {})
    token = os.getenv("NOTION_TOKEN")
    db_id = notion_settings.get("calendar_database_id", "")
    
    notion_success = False
    page_id = None
    notion_error_msg = ""
    
    # 1. Tenta la creazione su Notion se configurato
    if notion_settings.get("enabled", False) and token and db_id and NOTION_CLIENT_AVAILABLE:
        try:
            client = Client(auth=token)
            
            # Interroga lo schema del database o della data_source per mappare dinamicamente i campi
            is_data_source = False
            try:
                db_schema = client.databases.retrieve(database_id=db_id)
            except Exception as db_err:
                try:
                    db_schema = client.data_sources.retrieve(data_source_id=db_id)
                    is_data_source = True
                except Exception as ds_err:
                    raise db_err
            
            properties_schema = db_schema.get("properties", {})
            
            # Trova la chiave del titolo (tipo "title")
            title_name = next((k for k, v in properties_schema.items() if v.get("type") == "title"), None)
            
            # Trova la chiave della data (tipo "date")
            date_name = next((k for k, v in properties_schema.items() if v.get("type") == "date"), None)
            
            # Trova la chiave del luogo (se c'è una proprietà di tipo text/select che si chiama location/luogo)
            location_name = next((k for k, v in properties_schema.items() if k.lower() in ["location", "luogo", "posto"] and v.get("type") in ["rich_text", "select"]), None)
            location_type = properties_schema[location_name]["type"] if location_name else None
            
            if not title_name:
                raise ValueError("Nessuna proprietà di tipo 'title' trovata nel database Notion Calendar.")
                
            # Costruisci le proprietà per la creazione
            properties = {
                title_name: {"title": [{"text": {"content": title}}]}
            }
            
            if date_name and start_time:
                # Notion date start and optionally end
                date_val = {"start": start_time}
                if end_time:
                    date_val["end"] = end_time
                properties[date_name] = {"date": date_val}
                
            if location_name and location:
                if location_type == "rich_text":
                    properties[location_name] = {"rich_text": [{"text": {"content": location}}]}
                elif location_type == "select":
                    properties[location_name] = {"select": {"name": location}}
                    
            # Invia la richiesta di creazione
            parent = {"data_source_id": db_id} if is_data_source else {"database_id": db_id}
            new_page = client.pages.create(parent=parent, properties=properties)
            page_id = new_page["id"]
            notion_success = True
            print(f"Evento '{title}' creato con successo su Notion (Page ID: {page_id})")
        except Exception as e:
            notion_error_msg = str(e)
            print(f"Errore nella creazione dell'evento su Notion, fallback locale: {e}")
    else:
        if not token:
            notion_error_msg = "NOTION_TOKEN non impostato in .env"
        elif not db_id:
            notion_error_msg = "calendar_database_id non configurato in settings.md"
        elif not NOTION_CLIENT_AVAILABLE:
            notion_error_msg = "libreria 'notion-client' non installata"
        else:
            notion_error_msg = "Integrazione Notion disabilitata nelle impostazioni"
            
    # 2. Crea la nota locale nel vault Obsidian
    clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    if not clean_title:
        clean_title = f"Evento_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    local_rel_path = f"wiki/sources/Riunioni/{clean_title}.md"
    local_abs_path = os.path.join(vault_path, local_rel_path)
    os.makedirs(os.path.dirname(local_abs_path), exist_ok=True)
    
    quando = start_time[:10] if start_time else ""
    fm = {
        "type": "meeting",
        "title": title,
        "quando": quando,
        "start_time": start_time,
        "end_time": end_time or None,
        "location": location or None,
        "source": "notion" if notion_success else "local",
        "notion_page_id": page_id
    }
    
    body = f"# {title}\n\n"
    body += f"**Inizio**: {start_time}\n"
    if end_time:
        body += f"**Fine**: {end_time}\n"
    if location:
        body += f"**Luogo**: {location}\n"
    if not notion_success:
        body += f"\n*Nota: Questo evento è stato creato localmente (errore Notion: {notion_error_msg}).*\n"
        
    full_md = to_markdown(fm, body)
    
    with open(local_abs_path, "w", encoding="utf-8") as f:
        f.write(full_md)
        
    # Indicizzazione in tempo reale
    try:
        from engine.utils.vector_db import get_vector_db
        from engine.tools.embedder import chunk_text
        db = get_vector_db()
        db.upsert_chunks(local_rel_path, title, chunk_text(body))
    except Exception as e:
        print(f"Errore indicizzazione vettoriale per {local_abs_path}: {e}")
        
    # Auto-commit su Git
    try:
        from engine.git_ops import git_commit_file
        git_commit_file(local_rel_path, f"Crea riunione: {title}")
    except Exception:
        pass
        
    if notion_success:
        return f"Evento '{title}' creato con successo su Notion e salvato localmente nel vault in `{local_rel_path}`."
    else:
        return f"Evento '{title}' creato solo localmente nel vault in `{local_rel_path}` (Notion non disponibile: {notion_error_msg})."

if __name__ == "__main__":
    notion_calendar_sync()
