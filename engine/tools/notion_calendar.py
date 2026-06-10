import os
import datetime
from dotenv import load_dotenv
from engine.utils.markdown import load_settings, to_markdown

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
        dest_dir = os.path.join(vault_path, "raw", "calendar")
        os.makedirs(dest_dir, exist_ok=True)
        
        print(f"Interrogazione database Notion Calendar: {db_id}...")
        results = []
        has_more = True
        next_cursor = None
        
        while has_more:
            body = {}
            if next_cursor:
                body["start_cursor"] = next_cursor
            resp = client.request(path=f"databases/{db_id}/query", method="POST", body=body)
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
                
            clean_id = page_id.replace("-", "")
            filename = f"event_notion_{clean_id}.md"
            filepath = os.path.join(dest_dir, filename)
            
            # Format frontmatter
            fm = {
                "type": "calendar_event",
                "title": title,
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
                
            events_synced += 1
            
        return events_synced
        
    except Exception as e:
        print(f"Errore durante sincronizzazione Notion Calendar: {e}")
        return events_synced

if __name__ == "__main__":
    notion_calendar_sync()
