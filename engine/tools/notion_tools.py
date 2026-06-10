import os
import time
import datetime
from dotenv import load_dotenv
from engine.utils.markdown import load_settings

# Try importing notion_client
try:
    from notion_client import Client
    NOTION_CLIENT_AVAILABLE = True
except ImportError:
    NOTION_CLIENT_AVAILABLE = False

def get_vault_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def query_notion_database(client, db_id: str, body: dict = None) -> dict:
    """
    Risolve ed interroga un database Notion o la sua sorgente dati sottostante (data_source).
    """
    if body is None:
        body = {}
    try:
        db_meta = client.databases.retrieve(database_id=db_id)
        data_sources = db_meta.get("data_sources", [])
        if data_sources and isinstance(data_sources, list) and len(data_sources) > 0:
            ds_id = data_sources[0].get("id")
            if ds_id:
                return client.data_sources.query(data_source_id=ds_id, **body)
    except Exception as e:
        print(f"[NOTION] Errore retrieve per database {db_id}: {e}")
        
    return client.data_sources.query(data_source_id=db_id, **body)

def parse_notion_table_to_markdown(client, table_block_id: str, table_info: dict, indent: str) -> str:
    """
    Scarica i blocchi table_row di una tabella e genera la sintassi markdown della tabella.
    """
    rows = []
    has_more = True
    start_cursor = None
    
    while has_more:
        try:
            params = {"block_id": table_block_id}
            if start_cursor:
                params["start_cursor"] = start_cursor
            resp = client.blocks.children.list(**params)
            rows.extend(resp.get("results", []))
            has_more = resp.get("has_more", False)
            start_cursor = resp.get("next_cursor")
        except Exception as e:
            is_rate_limit = False
            if hasattr(e, "code") and e.code == "rate_limited":
                is_rate_limit = True
            elif hasattr(e, "status") and e.status == 429:
                is_rate_limit = True
                
            if is_rate_limit:
                print(f"Rate limited da Notion su tabella {table_block_id}. Attendo 5 secondi...")
                time.sleep(5)
                continue
            else:
                print(f"Errore nel recupero delle righe della tabella {table_block_id}: {e}")
                break
        time.sleep(0.15)
        
    if not rows:
        return ""
        
    table_lines = []
    has_header = table_info.get("has_column_header", False)
    
    # Processa ciascuna riga
    formatted_rows = []
    max_cols = 0
    
    for row in rows:
        if row.get("type") != "table_row":
            continue
        cells_data = row.get("table_row", {}).get("cells", [])
        row_cells = []
        for cell in cells_data:
            cell_text = "".join([t.get("plain_text", "") for t in cell]).replace("|", "\\|").replace("\n", "<br>")
            row_cells.append(cell_text)
        formatted_rows.append(row_cells)
        max_cols = max(max_cols, len(row_cells))
        
    if not formatted_rows:
        return ""
        
    # Allinea il numero di colonne per ciascuna riga
    for r in formatted_rows:
        while len(r) < max_cols:
            r.append("")
            
    # Genera la tabella markdown
    first_row = formatted_rows[0]
    table_lines.append(f"{indent}| " + " | ".join(first_row) + " |")
    
    # Riga separatore
    sep_cols = []
    for _ in range(max_cols):
        sep_cols.append("---")
    table_lines.append(f"{indent}| " + " | ".join(sep_cols) + " |")
    
    # Righe successive
    for r in formatted_rows[1:]:
        table_lines.append(f"{indent}| " + " | ".join(r) + " |")
        
    return "\n" + "\n".join(table_lines) + "\n"

def parse_notion_blocks_to_markdown(client, block_id: str, depth: int = 0) -> str:
    """
    Scarica ricorsivamente tutti i blocchi figli di un blocco Notion (o pagina)
    e li converte in markdown, gestendo la paginazione e i blocchi nidificati.
    """
    blocks = []
    has_more = True
    start_cursor = None
    
    while has_more:
        try:
            params = {"block_id": block_id}
            if start_cursor:
                params["start_cursor"] = start_cursor
            resp = client.blocks.children.list(**params)
            blocks.extend(resp.get("results", []))
            has_more = resp.get("has_more", False)
            start_cursor = resp.get("next_cursor")
        except Exception as e:
            is_rate_limit = False
            if hasattr(e, "code") and e.code == "rate_limited":
                is_rate_limit = True
            elif hasattr(e, "status") and e.status == 429:
                is_rate_limit = True
                
            if is_rate_limit:
                print(f"Rate limited da Notion per blocco {block_id}. Attendo 5 secondi...")
                time.sleep(5)
                continue
            else:
                print(f"Errore nel recupero dei blocchi per {block_id}: {e}")
                break
            
        time.sleep(0.15)
        
    md_lines = []
    indent = "    " * depth
    
    for block in blocks:
        b_type = block.get("type")
        if not b_type:
            continue
            
        has_children = block.get("has_children", False)
        
        # 1. Parsing in base al tipo di blocco
        if b_type == "paragraph":
            rich_text = block.get("paragraph", {}).get("rich_text", [])
            text = "".join([t.get("plain_text", "") for t in rich_text])
            if text.strip() or has_children:
                md_lines.append(f"{indent}{text}")
                
        elif b_type == "heading_1":
            rich_text = block.get("heading_1", {}).get("rich_text", [])
            text = "".join([t.get("plain_text", "") for t in rich_text])
            md_lines.append(f"\n{indent}# {text}\n")
            
        elif b_type == "heading_2":
            rich_text = block.get("heading_2", {}).get("rich_text", [])
            text = "".join([t.get("plain_text", "") for t in rich_text])
            md_lines.append(f"\n{indent}## {text}\n")
            
        elif b_type == "heading_3":
            rich_text = block.get("heading_3", {}).get("rich_text", [])
            text = "".join([t.get("plain_text", "") for t in rich_text])
            md_lines.append(f"\n{indent}### {text}\n")
            
        elif b_type == "bulleted_list_item":
            rich_text = block.get("bulleted_list_item", {}).get("rich_text", [])
            text = "".join([t.get("plain_text", "") for t in rich_text])
            md_lines.append(f"{indent}- {text}")
            
        elif b_type == "numbered_list_item":
            rich_text = block.get("numbered_list_item", {}).get("rich_text", [])
            text = "".join([t.get("plain_text", "") for t in rich_text])
            md_lines.append(f"{indent}1. {text}")
            
        elif b_type == "to_do":
            rich_text = block.get("to_do", {}).get("rich_text", [])
            checked = block.get("to_do", {}).get("checked", False)
            text = "".join([t.get("plain_text", "") for t in rich_text])
            status = "[x]" if checked else "[ ]"
            md_lines.append(f"{indent}- {status} {text}")
            
        elif b_type == "quote":
            rich_text = block.get("quote", {}).get("rich_text", [])
            text = "".join([t.get("plain_text", "") for t in rich_text])
            md_lines.append(f"{indent}> {text}")
            
        elif b_type == "callout":
            rich_text = block.get("callout", {}).get("rich_text", [])
            text = "".join([t.get("plain_text", "") for t in rich_text])
            md_lines.append(f"\n{indent}> [!NOTE]\n{indent}> {text.replace(chr(10), chr(10) + indent + '> ')}\n")
            
        elif b_type == "code":
            rich_text = block.get("code", {}).get("rich_text", [])
            text = "".join([t.get("plain_text", "") for t in rich_text])
            lang = block.get("code", {}).get("language", "plaintext")
            md_lines.append(f"\n{indent}```{lang}\n{indent}{text}\n{indent}```\n")
            
        elif b_type == "divider":
            md_lines.append(f"\n{indent}---\n")
            
        elif b_type in ["image", "file", "pdf"]:
            file_data = block.get(b_type, {})
            file_type = file_data.get("type")
            url = ""
            if file_type == "external":
                url = file_data.get("external", {}).get("url", "")
            elif file_type == "file":
                url = file_data.get("file", {}).get("url", "")
                
            caption_list = file_data.get("caption", [])
            caption = "".join([t.get("plain_text", "") for t in caption_list]) or b_type
            
            if url:
                if b_type == "image":
                    md_lines.append(f"{indent}![{caption}]({url})")
                else:
                    md_lines.append(f"{indent}[{caption}]({url})")
                    
        elif b_type == "table":
            table_md = parse_notion_table_to_markdown(client, block["id"], block.get("table", {}), indent)
            if table_md:
                md_lines.append(table_md)
            has_children = False
            
        elif b_type == "toggle":
            rich_text = block.get("toggle", {}).get("rich_text", [])
            text = "".join([t.get("plain_text", "") for t in rich_text])
            md_lines.append(f"{indent}**{text}**")
            
        elif b_type in ["child_page", "child_database"]:
            title = block.get(b_type, {}).get("title", "Sotto-pagina / Sotto-database")
            md_lines.append(f"{indent}*[[Notion child: {title}]]*")
            
        else:
            block_data = block.get(b_type, {})
            if isinstance(block_data, dict) and "rich_text" in block_data:
                rich_text = block_data.get("rich_text", [])
                text = "".join([t.get("plain_text", "") for t in rich_text])
                if text.strip():
                    md_lines.append(f"{indent}{text}")
                    
        # 2. Gestione della ricorsione per i figli
        if has_children and b_type != "table":
            children_md = parse_notion_blocks_to_markdown(client, block["id"], depth + 1)
            if children_md.strip():
                md_lines.append(children_md)
                
    return "\n".join(md_lines)

def notion_sync_to_raw() -> int:
    """
    Sincronizza le pagine dei database Notion specificati in settings.md o tutte le pagine (se sync_all è true)
    salvandole in raw/notion/ in formato markdown.
    Ritorna il numero di pagine sincronizzate.
    """
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
        
    db_ids = notion_settings.get("database_ids", [])
    sync_all = notion_settings.get("sync_all", False)
    
    if not sync_all and not db_ids:
        print("Nessun database_id impostato per Notion in settings.md e sync_all è disabilitato.")
        return 0
        
    if not NOTION_CLIENT_AVAILABLE:
        print("Libreria 'notion-client' non installata. Salto sincronizzazione Notion.")
        return 0
        
    pages_synced = 0
    try:
        client = Client(auth=token)
        raw_notion_dir = os.path.join(vault_path, "raw", "notion")
        os.makedirs(raw_notion_dir, exist_ok=True)
        
        results = []
        
        # 1. Interroga i database specificati se presenti
        if db_ids:
            for db_id in db_ids:
                print(f"Interrogazione database Notion paginato: {db_id}...")
                db_results = []
                try:
                    has_more = True
                    next_cursor = None
                    while has_more:
                        body = {}
                        if next_cursor:
                            body["start_cursor"] = next_cursor
                        resp = query_notion_database(client, db_id, body)
                        db_results.extend(resp.get("results", []))
                        has_more = resp.get("has_more", False)
                        next_cursor = resp.get("next_cursor")
                except Exception as e:
                    print(f"Errore durante l'interrogazione del database {db_id}: {e}")
                results.extend(db_results)
                    
        # 2. Se sync_all è abilitato, esegui anche la ricerca globale per altre pagine
        if sync_all:
            print("Sincronizzazione tramite ricerca globale (client.search) con paginazione completa...")
            try:
                has_more = True
                next_cursor = None
                while has_more:
                    params = {"filter": {"property": "object", "value": "page"}}
                    if next_cursor:
                        params["start_cursor"] = next_cursor
                    search_resp = client.search(**params)
                    search_results = search_resp.get("results", [])
                    for r in search_results:
                        if r.get("object") == "page":
                            results.append(r)
                    has_more = search_resp.get("has_more", False)
                    next_cursor = search_resp.get("next_cursor")
            except Exception as e:
                print(f"Errore nella ricerca globale: {e}")

        # Rimuovi duplicati basandoti sull'ID pagina
        unique_results = []
        seen_ids = set()
        for r in results:
            r_id = r.get("id")
            if r_id and r_id not in seen_ids:
                seen_ids.add(r_id)
                unique_results.append(r)
        results = unique_results
                
        print(f"Trovate {len(results)} pagine totali in Notion. Inizio elaborazione/aggiornamento locale...")
        
        for page in results:
            page_id = page["id"]
            title = "Senza titolo"
            
            # Estrai last_edited_time da Notion per ottimizzazione skip
            last_edited_str = page.get("last_edited_time", "")
            remote_epoch = 0
            if last_edited_str:
                try:
                    remote_time = datetime.datetime.fromisoformat(last_edited_str.replace("Z", "+00:00"))
                    remote_epoch = remote_time.timestamp()
                except Exception:
                    pass
            
            filename = f"{page_id.replace('-', '')}.md"
            filepath = os.path.join(raw_notion_dir, filename)
            
            # Se il file locale esiste ed è stato modificato dopo l'ultima modifica remota, salta il download
            if os.path.exists(filepath) and os.path.getmtime(filepath) >= remote_epoch:
                pages_synced += 1
                continue
                
            # Estrai il titolo
            properties = page.get("properties", {})
            for prop_name, prop_data in properties.items():
                if prop_data.get("type") == "title":
                    title_list = prop_data.get("title", [])
                    if title_list:
                        title = "".join([t.get("plain_text", "") for t in title_list])
                        break
                        
            print(f"Download e aggiornamento pagina Notion: '{title}' -> {filename}...")
            
            # Get blocks (page content) using recursive parser
            try:
                body_content = parse_notion_blocks_to_markdown(client, page_id)
            except Exception as e:
                print(f"Errore nel recupero dei blocchi per la pagina {title} ({page_id}): {e}")
                continue
                
            md_content = f"# {title}\n\nSource: Notion (ID: {page_id})\n\n{body_content}"
            
            # Scrivi il file markdown
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(md_content)
                
            pages_synced += 1
            
        return pages_synced
        
    except Exception as e:
        print(f"Errore durante la sincronizzazione da Notion: {e}")
        return pages_synced
