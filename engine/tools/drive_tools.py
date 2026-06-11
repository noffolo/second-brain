import os
import shutil
import urllib.request
import urllib.parse
import json
import re
import ssl
from engine.utils.markdown import load_settings

try:
    ssl_context = ssl._create_unverified_context()
except AttributeError:
    ssl_context = None

# Try importing fitz (PyMuPDF) and docx
try:
    import fitz # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    import docx
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

def get_vault_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def extract_pdf_text(filepath: str) -> str:
    if not PYMUPDF_AVAILABLE:
        return "[Errore: PyMuPDF non installato. Impossibile estrarre testo da PDF]"
    try:
        doc = fitz.open(filepath)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        return "\n".join(text_parts)
    except Exception as e:
        return f"[Errore durante l'estrazione del PDF: {e}]"

def extract_docx_text(filepath: str) -> str:
    if not DOCX_AVAILABLE:
        return "[Errore: python-docx non installato. Impossibile estrarre testo da Word]"
    try:
        doc = docx.Document(filepath)
        text_parts = []
        for paragraph in doc.paragraphs:
            text_parts.append(paragraph.text)
        return "\n".join(text_parts)
    except Exception as e:
        return f"[Errore durante l'estrazione del Word: {e}]"

def get_drive_access_token() -> str:
    """
    Ottiene un token OAuth 2.0 di accesso usando Application Default Credentials (ADC).
    Legge automaticamente GOOGLE_APPLICATION_CREDENTIALS o le credenziali di gcloud.
    """
    try:
        import google.auth
        from google.auth.transport.requests import Request as AuthRequest
        
        # Scope per la lettura dei file di Google Drive
        scopes = ["https://www.googleapis.com/auth/drive.readonly"]
        credentials, project = google.auth.default(scopes=scopes)
        
        # Esegui il refresh delle credenziali per ottenere il token di accesso
        credentials.refresh(AuthRequest())
        return credentials.token
    except Exception as e:
        print(f"Nota: Impossibile ottenere il token OAuth/ADC da google.auth ({e}).")
        return None

def download_drive_file(file_id: str, file_name: str, mime_type: str, file_resource_key: str, api_key: str, access_token: str, dest_dir: str) -> str:
    is_google_doc = mime_type.startswith("application/vnd.google-apps.")
    
    params = {}
    if is_google_doc:
        # Esporta i Google Doc in formato Docx, Spreadsheet in CSV, altri in PDF
        if "document" in mime_type:
            export_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ext = ".docx"
        elif "spreadsheet" in mime_type:
            export_mime = "text/csv"
            ext = ".csv"
        else:
            export_mime = "application/pdf"
            ext = ".pdf"
            
        params["mimeType"] = export_mime
        if api_key and not access_token:
            params["key"] = api_key
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export?" + urllib.parse.urlencode(params)
    else:
        # Download dei file binari normali
        params["alt"] = "media"
        if api_key and not access_token:
            params["key"] = api_key
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?" + urllib.parse.urlencode(params)
        _, ext = os.path.splitext(file_name.lower())
        if not ext:
            ext = ".bin"
            
    req = urllib.request.Request(url)
    if access_token:
        req.add_header("Authorization", f"Bearer {access_token}")
    if file_resource_key:
        req.add_header("X-Goog-Drive-Resource-Keys", f"{file_id}={file_resource_key}")
        
    try:
        with urllib.request.urlopen(req, context=ssl_context) as response:
            content = response.read()
            
        # Pulisci il nome del file
        clean_name = re.sub(r'[\\/*?:"<>|]', "", file_name)
        if not clean_name.lower().endswith(ext.lower()):
            clean_name += ext
            
        temp_filepath = os.path.join(dest_dir, clean_name)
        with open(temp_filepath, "wb") as f:
            f.write(content)
            
        return temp_filepath
    except Exception as e:
        print(f"Errore nel download del file {file_name} ({file_id}): {e}")
        return None

def drive_sync_from_api(folder_id: str, resource_key: str, api_key: str, access_token: str) -> int:
    """
    Sincronizza i file di Google Drive usando le API REST di Google Drive con autenticazione OAuth o API Key.
    """
    vault_path = get_vault_path()
    raw_drive_dir = os.path.join(vault_path, "raw", "drive")
    os.makedirs(raw_drive_dir, exist_ok=True)
    
    temp_download_dir = os.path.join(vault_path, "raw", "drive_temp_downloads")
    os.makedirs(temp_download_dir, exist_ok=True)
    
    files_synced = 0
    try:
        query = f"'{folder_id}' in parents and trashed = false"
        params = {
            "q": query,
            "fields": "files(id, name, mimeType, resourceKey)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true"
        }
        if api_key and not access_token:
            params["key"] = api_key
            
        url = "https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode(params)
        
        req = urllib.request.Request(url)
        if access_token:
            req.add_header("Authorization", f"Bearer {access_token}")
        if resource_key:
            req.add_header("X-Goog-Drive-Resource-Keys", f"{folder_id}={resource_key}")
            
        with urllib.request.urlopen(req, context=ssl_context) as response:
            data = json.loads(response.read().decode())
            files = data.get("files", [])
            
        for drive_file in files:
            file_id = drive_file.get("id")
            file_name = drive_file.get("name")
            mime_type = drive_file.get("mimeType")
            file_rkey = drive_file.get("resourceKey")
            
            if not file_id or not file_name:
                continue
                
            dest_filename = file_name + ".md"
            dest_filepath = os.path.join(raw_drive_dir, dest_filename)
            
            # Salta se già sincronizzato
            if os.path.exists(dest_filepath):
                continue
                
            print(f"Sincronizzazione file da API Drive: {file_name}...")
            
            # Scarica il file
            temp_filepath = download_drive_file(file_id, file_name, mime_type, file_rkey, api_key, access_token, temp_download_dir)
            if not temp_filepath:
                continue
                
            # Estrai il testo in base all'estensione
            _, ext = os.path.splitext(temp_filepath.lower())
            
            if ext in [".txt", ".md"]:
                with open(temp_filepath, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                with open(dest_filepath, "w", encoding="utf-8") as f:
                    f.write(f"# {file_name}\n\n{text}")
            elif ext == ".pdf":
                text = extract_pdf_text(temp_filepath)
                with open(dest_filepath, "w", encoding="utf-8") as f:
                    f.write(f"# {file_name} (PDF Extracted)\n\n{text}")
            elif ext in [".docx", ".doc"]:
                text = extract_docx_text(temp_filepath)
                with open(dest_filepath, "w", encoding="utf-8") as f:
                    f.write(f"# {file_name} (Word Extracted)\n\n{text}")
            else:
                try:
                    os.remove(temp_filepath)
                except Exception:
                    pass
                continue
                
            try:
                os.remove(temp_filepath)
            except Exception:
                pass
                
            files_synced += 1
            print(f"Sincronizzato {file_name} -> {dest_filename}")
            
        try:
            os.rmdir(temp_download_dir)
        except Exception:
            pass
            
        return files_synced
    except Exception as e:
        print(f"Errore durante la sincronizzazione da Drive API: {e}")
        return files_synced

def drive_sync_to_raw() -> int:
    """
    Sincronizza Google Drive salvando i file estratti in raw/drive/.
    Supporta la sincronizzazione locale (Desktop App) e quella tramite REST API.
    """
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    
    drive_settings = settings.get("sources", {}).get("google_drive", {})
    if not drive_settings.get("enabled", False):
        print("Sorgente Google Drive disabilitata nelle impostazioni.")
        return 0
        
    use_api = drive_settings.get("use_api", False)
    if use_api:
        folder_id = drive_settings.get("folder_id", "")
        resource_key = drive_settings.get("resource_key", "")
        
        # Prova ad acquisire il token OAuth/ADC (es. tramite GOOGLE_APPLICATION_CREDENTIALS)
        access_token = get_drive_access_token()
        
        api_key = None
        if not access_token:
            # Fallback sulla chiave API
            from engine.utils.llm_fallback import resolve_gemini_key
            api_key = resolve_gemini_key()
            if not api_key or "YOUR_GEMINI" in api_key:
                print("Errore: Impossibile sincronizzare Google Drive. Nessun token OAuth/ADC trovato e GEMINI_API_KEY non impostata.")
                return 0
                
        if not folder_id:
            print("Errore: folder_id non impostato in settings.md per la sincronizzazione API di Google Drive.")
            return 0
            
        return drive_sync_from_api(folder_id, resource_key, api_key, access_token)
        
    # Sincronizzazione locale ricorsiva (App Desktop)
    local_path = drive_settings.get("local_path", "")
    if not local_path:
        print("Errore: local_path non impostato per Google Drive in settings.md.")
        return 0
        
    local_path = os.path.expanduser(local_path)
    if not os.path.exists(local_path):
        print(f"Errore: Il percorso Google Drive locale '{local_path}' non esiste.")
        return 0
        
    raw_drive_dir = os.path.join(vault_path, "raw", "drive")
    os.makedirs(raw_drive_dir, exist_ok=True)
    
    files_synced = 0
    try:
        for root, dirs, files in os.walk(local_path):
            # Escludi le cartelle nascoste modificando dirs in-place
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            
            for file in files:
                if file.startswith("."):
                    continue
                    
                filepath = os.path.join(root, file)
                
                # Calcola il percorso relativo per evitare collisioni di file omonimi
                rel_path = os.path.relpath(filepath, local_path)
                clean_rel_name = rel_path.replace(os.sep, "_")
                dest_filename = clean_rel_name + ".md"
                dest_filepath = os.path.join(raw_drive_dir, dest_filename)
                
                # Sincronizzazione incrementale: salta se la nota esiste ed è più recente del file originale
                if os.path.exists(dest_filepath):
                    try:
                        if os.path.getmtime(filepath) <= os.path.getmtime(dest_filepath):
                            continue
                    except Exception:
                        pass
                        
                print(f"Sincronizzazione file Drive locale ricorsivo: {rel_path}...")
                
                _, ext = os.path.splitext(file.lower())
                text = ""
                
                if ext in [".txt", ".md"]:
                    try:
                        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                            text = f.read()
                    except Exception as e:
                        text = f"[Errore lettura file di testo: {e}]"
                elif ext == ".pdf":
                    text = extract_pdf_text(filepath)
                elif ext in [".docx", ".doc"]:
                    text = extract_docx_text(filepath)
                else:
                    continue
                    
                clean_rel_path = rel_path.replace('"', '\\"')
                clean_file = file.replace('"', '\\"')
                
                md_content = f"""---
type: drive_file
original_path: "{clean_rel_path}"
filename: "{clean_file}"
---

# {file}

**Percorso originale**: `{rel_path}`

{text}
"""
                with open(dest_filepath, "w", encoding="utf-8") as f:
                    f.write(md_content)
                    
                files_synced += 1
                print(f"Sincronizzato {rel_path} -> {dest_filename}")
                
        return files_synced
        
    except Exception as e:
        print(f"Errore durante la sincronizzazione da Drive locale: {e}")
        return files_synced
