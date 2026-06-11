import os
import sys
import datetime
import json
import re
from dotenv import load_dotenv

# Try importing notion_client
try:
    from notion_client import Client
    NOTION_CLIENT_AVAILABLE = True
except ImportError:
    NOTION_CLIENT_AVAILABLE = False

from engine.utils.markdown import load_settings, to_markdown
from engine.tools.notion_tools import query_notion_database, parse_notion_blocks_to_markdown
from engine.tools.vault_tools import get_vault_path, save_processed_file, update_index

def parse_notion_date(date_prop: dict) -> str:
    if not date_prop or date_prop.get("type") != "date" or not date_prop.get("date"):
        return ""
    date_data = date_prop["date"]
    start_str = date_data.get("start", "")
    if "T" in start_str:
        return start_str.split("T")[0]
    return start_str

def get_notion_text_prop(prop: dict) -> str or list[str] or bool or float:
    if not prop:
        return ""
    p_type = prop.get("type")
    if p_type == "rich_text":
        return "".join([t.get("plain_text", "") for t in prop.get("rich_text", [])])
    elif p_type == "select":
        select_data = prop.get("select")
        return select_data.get("name", "") if select_data else ""
    elif p_type == "multi_select":
        return [x.get("name", "") for x in prop.get("multi_select", [])]
    elif p_type == "checkbox":
        return prop.get("checkbox", False)
    elif p_type == "number":
        return prop.get("number")
    elif p_type == "url":
        return prop.get("url", "")
    elif p_type == "people":
        return [x.get("name", "") for x in prop.get("people", []) if x.get("name")]
    elif p_type == "last_edited_time":
        return prop.get("last_edited_time", "")
    elif p_type == "date":
        return parse_notion_date(prop)
    return ""

def get_notion_relation_prop(prop: dict, id_to_title: dict) -> list[str]:
    if not prop or prop.get("type") != "relation":
        return []
    relations = prop.get("relation", [])
    rel_titles = []
    for r in relations:
        r_id = r.get("id")
        if r_id:
            title = id_to_title.get(r_id)
            if title:
                rel_titles.append(f"[[{title}]]")
    return rel_titles

def get_notion_title(page: dict) -> str:
    properties = page.get("properties", {})
    for prop_name, prop_data in properties.items():
        if prop_data.get("type") == "title":
            title_list = prop_data.get("title", [])
            if title_list:
                return "".join([t.get("plain_text", "") for t in title_list]).strip()
    return "Senza titolo"

def build_id_to_title_map_from_vault() -> dict:
    id_to_title = {}
    vault_path = get_vault_path()
    folder_mapping = {
        "Clienti": "wiki/entities/Clienti",
        "Progetti": "wiki/entities/Progetti",
        "Task": "wiki/entities/Task",
        "Riunioni": "wiki/sources/Riunioni",
        "Documenti": "wiki/sources/Documenti",
        "Link": "wiki/sources/Link"
    }
    
    from engine.utils.markdown import parse_markdown
    for name, folder in folder_mapping.items():
        abs_folder = os.path.join(vault_path, folder)
        if not os.path.exists(abs_folder):
            continue
        for root, _, files in os.walk(abs_folder):
            for file in files:
                if file.endswith(".md"):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        fm, _ = parse_markdown(content)
                        notion_id = fm.get("notion_page_id")
                        title = fm.get("title")
                        if notion_id and title:
                            id_to_title[notion_id] = title
                            id_to_title[notion_id.replace("-", "")] = title
                    except Exception:
                        pass
    return id_to_title

def notion_all_db_sync() -> int:
    load_dotenv()
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    
    notion_settings = settings.get("sources", {}).get("notion", {})
    if not notion_settings.get("enabled", False):
        print("Sorgente Notion disabilitata nelle impostazioni.")
        return 0
        
    token = os.getenv("NOTION_TOKEN")
    if not token:
        print("Errore: NOTION_TOKEN non impostato nel file .env.")
        return 0
        
    db_ids = {
        "Clienti": "6f4bd393f5394cd9ae70eeb83df9ed79",
        "Progetti": "8cf4fdfcd0e0471e82b37b323e597965",
        "Task": "d73ddfa6f4524279be2b2956a17aab45",
        "Riunioni": "eaabfc93f45548779832470db0ea60e9",
        "Documenti": "9a5507065830472a9084673433fe825b",
        "Link": "53eb57f933814e0ab375748b120ce121"
    }
    
    if not NOTION_CLIENT_AVAILABLE:
        print("Libreria 'notion-client' non installata. Salto sincronizzazione Notion DB.")
        return 0
        
    client = Client(auth=token)
    
    # 1. Costruzione mappa ID-Titolo dal vault locale e interrogazione incrementale
    print("Costruzione della mappa ID-Titolo dal vault locale...")
    id_to_title = build_id_to_title_map_from_vault()
    all_pages_by_db = {name: [] for name in db_ids}
    
    folder_mapping = {
        "Clienti": "wiki/entities/Clienti",
        "Progetti": "wiki/entities/Progetti",
        "Task": "wiki/entities/Task",
        "Riunioni": "wiki/sources/Riunioni",
        "Documenti": "wiki/sources/Documenti",
        "Link": "wiki/sources/Link"
    }
    
    for name, db_id in db_ids.items():
        folder_path = os.path.join(vault_path, folder_mapping.get(name, ""))
        has_local_files = False
        if os.path.exists(folder_path):
            has_local_files = any(f.endswith(".md") for f in os.listdir(folder_path))
            
        print(f"Interrogazione Notion database '{name}' ({db_id})...")
        try:
            has_more = True
            next_cursor = None
            while has_more:
                body = {}
                if next_cursor:
                    body["start_cursor"] = next_cursor
                    
                if has_local_files:
                    seven_days_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).isoformat()
                    body["filter"] = {
                        "timestamp": "last_edited_time",
                        "last_edited_time": {
                            "on_or_after": seven_days_ago
                        }
                    }
                    
                resp = query_notion_database(client, db_id, body)
                results = resp.get("results", [])
                all_pages_by_db[name].extend(results)
                
                for page in results:
                    p_id = page["id"]
                    p_title = get_notion_title(page)
                    id_to_title[p_id] = p_title
                    id_to_title[p_id.replace("-", "")] = p_title
                    
                has_more = resp.get("has_more", False)
                next_cursor = resp.get("next_cursor")
        except Exception as e:
            print(f"Errore querying {name}: {e}")
            
    print(f"Mappati {len(id_to_title)} ID a titoli.")
    
    # 2. Process and compile pages for each database
    total_synced = 0
    
    for name, pages in all_pages_by_db.items():
        print(f"\nElaborazione database {name} ({len(pages)} elementi)...")
        for page in pages:
            page_id = page["id"]
            title = get_notion_title(page)
            if not title or title == "Senza titolo":
                continue
                
            # Clean title for filename
            clean_title = re.sub(r'[\\/*?:"<>|]', "", title)
            
            # Extract last_edited_time
            last_edited_str = page.get("last_edited_time", "")
            remote_epoch = 0
            if last_edited_str:
                try:
                    remote_epoch = datetime.datetime.fromisoformat(last_edited_str.replace("Z", "+00:00")).timestamp()
                except Exception:
                    pass
            
            # Resolve target path in wiki/ and relative raw path for manifest
            if name == "Clienti":
                wiki_rel_path = f"wiki/entities/Clienti/{clean_title}.md"
                doc_type = "client"
            elif name == "Progetti":
                wiki_rel_path = f"wiki/entities/Progetti/{clean_title}.md"
                doc_type = "project"
            elif name == "Task":
                wiki_rel_path = f"wiki/entities/Task/{clean_title}.md"
                doc_type = "task"
            elif name == "Riunioni":
                wiki_rel_path = f"wiki/sources/Riunioni/{clean_title}.md"
                doc_type = "meeting"
            elif name == "Documenti":
                wiki_rel_path = f"wiki/sources/Documenti/{clean_title}.md"
                doc_type = "document"
            elif name == "Link":
                wiki_rel_path = f"wiki/sources/Link/{clean_title}.md"
                doc_type = "link"
            else:
                continue
                
            wiki_abs_path = os.path.join(vault_path, wiki_rel_path)
            
            # Optimization: check if local file is newer than remote modification
            if os.path.exists(wiki_abs_path) and os.path.getmtime(wiki_abs_path) >= remote_epoch:
                total_synced += 1
                continue
                
            # Parse properties
            properties = page.get("properties", {})
            fm_props = {
                "type": doc_type,
                "title": title,
                "source": "notion",
                "notion_page_id": page_id
            }
            
            for prop_name, prop_data in properties.items():
                p_type = prop_data.get("type")
                # Normalize key name for YAML (lowercase, alphanumeric, underscores)
                clean_key = re.sub(r'[^a-zA-Z0-9_]', '', prop_name.replace(" ", "_").lower())
                if not clean_key:
                    continue
                    
                if p_type == "relation":
                    fm_props[clean_key] = get_notion_relation_prop(prop_data, id_to_title)
                else:
                    val = get_notion_text_prop(prop_data)
                    fm_props[clean_key] = val if val is not None else None
            
            # Fetch page body blocks
            print(f"  Fetching content for '{title}'...")
            try:
                body_content = parse_notion_blocks_to_markdown(client, page_id)
            except Exception as e:
                print(f"  Errore fetching content per {title}: {e}")
                body_content = ""
                
            # Format Markdown
            body_text = f"# {title}\n\n"
            
            # Print properties nicely
            for prop_name, prop_data in properties.items():
                p_type = prop_data.get("type")
                if p_type == "title":
                    continue
                if p_type == "relation":
                    rels = get_notion_relation_prop(prop_data, id_to_title)
                    if rels:
                        body_text += f"**{prop_name}**: {', '.join(rels)}\n"
                else:
                    val = get_notion_text_prop(prop_data)
                    if val or val is True or val == 0:
                        if isinstance(val, list):
                            body_text += f"**{prop_name}**: {', '.join(map(str, val))}\n"
                        else:
                            body_text += f"**{prop_name}**: {val}\n"
                            
            if body_content.strip():
                body_text += f"\n---\n\n{body_content}\n"
                
            # Write markdown
            os.makedirs(os.path.dirname(wiki_abs_path), exist_ok=True)
            full_md = to_markdown(fm_props, body_text)
            with open(wiki_abs_path, "w", encoding="utf-8") as f:
                f.write(full_md)
                
            # Indicizzazione in tempo reale in ChromaDB
            try:
                from engine.utils.vector_db import get_vector_db
                from engine.tools.embedder import chunk_text
                db = get_vector_db()
                db.upsert_chunks(wiki_rel_path, title, chunk_text(body_text))
            except Exception as e:
                print(f"  Errore indicizzazione vettoriale per {wiki_rel_path}: {e}")
                
            # Set mtime to remote modification time
            os.utime(wiki_abs_path, (remote_epoch, remote_epoch))
            
            # Mark raw notion paths as processed to prevent the Ingest Agent from processing them
            raw_notion_path = f"raw/notion/{page_id.replace('-', '')}.md"
            save_processed_file(raw_notion_path)
            
            # Also mark raw calendar path as processed if this was a meeting
            if name == "Riunioni":
                raw_cal_path = f"raw/calendar/event_notion_{page_id.replace('-', '')}.md"
                save_processed_file(raw_cal_path)
                
            # Update index
            update_index(wiki_rel_path, body_content[:150].strip().replace("\n", " ") if body_content else "")
            
            total_synced += 1
            
    return total_synced

if __name__ == "__main__":
    notion_all_db_sync()
