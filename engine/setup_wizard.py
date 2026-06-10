import os
import sys
import smtplib
import imaplib
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv, set_key
from notion_client import Client
from engine.utils.markdown import load_settings, parse_markdown, to_markdown

def get_vault_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def save_settings(vault_path: str, settings: dict):
    settings_file = os.path.join(vault_path, "settings.md")
    body = ""
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                _, body = parse_markdown(f.read())
        except Exception:
            pass
    if not body:
        body = "\n# Configurazione del Secondo Cervello\n\nQuesto file contiene i parametri di configurazione del Secondo Cervello.\n"
    
    full_md = to_markdown(settings, body)
    with open(settings_file, "w", encoding="utf-8") as f:
        f.write(full_md)

def set_env_value(key: str, value: str):
    env_path = os.path.join(get_vault_path(), ".env")
    if not os.path.exists(env_path):
        with open(env_path, "w") as f:
            f.write("")
    set_key(env_path, key, value)

def test_google_studio_key(key: str) -> bool:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
    payload = {"contents": [{"parts": [{"text": "Hello"}]}]}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 200
    except Exception:
        return False

def test_ollama_host(host: str) -> bool:
    url = f"{host.rstrip('/')}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status == 200
    except Exception:
        return False

def run_setup_wizard():
    print("\n" + "="*50)
    print("      WIZARD DI CONFIGURAZIONE SECONDO CERVELLO")
    print("="*50 + "\n")
    
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    load_dotenv(os.path.join(vault_path, ".env"))
    
    # 1. Configurazione LLM
    print("--- 1. CONFIGURAZIONE MODELLO GENERATIVO (LLM) ---")
    print("Scegli il provider principale per l'LLM:")
    print("1) Google AI Studio (Gemini con API Key)")
    print("2) Google Cloud Vertex AI (Gemini con Google Auth / ADC)")
    print("3) Ollama (Modello locale, es. Llama3)")
    print("4) DeepSeek (DeepSeek API Key)")
    
    choice = input("Seleziona un'opzione (1-4) [predefinito: 1]: ").strip() or "1"
    
    # Reimposta i default
    settings["google_auth"]["use_vertex"] = False
    set_env_value("BYPASS_GEMINI", "false")
    set_env_value("OLLAMA_ENABLED", "false")
    
    if choice == "1":
        current_key = os.getenv("GEMINI_API_KEY", "")
        print(f"Inserisci la tua GEMINI_API_KEY [attuale: {current_key[:10]}...]: ", end="")
        key = input().strip() or current_key
        if key:
            print("Validazione della chiave API in corso...")
            if test_google_studio_key(key):
                print("-> Chiave API validata con successo!")
                set_env_value("GEMINI_API_KEY", key)
                settings["models"]["ingest_agent"] = "gemini-3.5-flash"
                settings["models"]["query_agent"] = "gemini-3.5-flash"
            else:
                print("-> [WARNING] La validazione della chiave ha fallito. La chiave è stata salvata comunque.")
                set_env_value("GEMINI_API_KEY", key)
        else:
            print("Nessuna chiave inserita. Si utilizzeranno i fallback o le configurazioni esistenti.")
            
    elif choice == "2":
        settings["google_auth"]["use_vertex"] = True
        project_id = input("Inserisci l'ID del progetto Google Cloud (project_id): ").strip()
        location = input("Inserisci la regione di Vertex AI [us-central1]: ").strip() or "us-central1"
        if project_id:
            settings["google_auth"]["project_id"] = project_id
        settings["google_auth"]["location"] = location
        settings["models"]["ingest_agent"] = "gemini-3.5-flash"
        settings["models"]["query_agent"] = "gemini-3.5-flash"
        print("Vertex AI configurato. Assicurati di aver eseguito 'gcloud auth application-default login' per autenticarti.")
        
    elif choice == "3":
        set_env_value("OLLAMA_ENABLED", "true")
        current_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        host = input(f"Inserisci l'indirizzo host di Ollama [{current_host}]: ").strip() or current_host
        current_model = os.getenv("OLLAMA_MODEL", "llama3")
        model = input(f"Inserisci il nome del modello locale da utilizzare [{current_model}]: ").strip() or current_model
        
        print(f"Validazione della connessione a Ollama presso {host}...")
        if test_ollama_host(host):
            print("-> Connessione a Ollama stabilita con successo!")
        else:
            print("-> [WARNING] Ollama non risponde. Controlla che il demone sia attivo. Salvato comunque.")
            
        set_env_value("OLLAMA_HOST", host)
        set_env_value("OLLAMA_MODEL", model)
        settings["models"]["ingest_agent"] = f"ollama/{model}"
        settings["models"]["query_agent"] = f"ollama/{model}"
        
    elif choice == "4":
        set_env_value("BYPASS_GEMINI", "true")
        current_key = os.getenv("DEEPSEEK_API_KEY", "")
        print(f"Inserisci la tua DEEPSEEK_API_KEY [attuale: {current_key[:10]}...]: ", end="")
        key = input().strip() or current_key
        if key:
            set_env_value("DEEPSEEK_API_KEY", key)
            print("DeepSeek salvato ed abilitato.")
            settings["models"]["ingest_agent"] = "deepseek-chat"
            settings["models"]["query_agent"] = "deepseek-chat"
            
    print("\n--- 2. INTEGRAZIONE NOTION & DATABASE MAPPING ---")
    current_token = os.getenv("NOTION_TOKEN", "")
    token = input(f"Inserisci il tuo NOTION_TOKEN [attuale: {current_token[:10]}...]: ").strip() or current_token
    
    if token:
        set_env_value("NOTION_TOKEN", token)
        print("Connessione a Notion in corso...")
        try:
            client = Client(auth=token)
            resp = client.search(filter={"property": "object", "value": "database"})
            databases = resp.get("results", [])
            
            if databases:
                print(f"Trovati {len(databases)} database condivisi con l'integrazione:")
                for idx, db in enumerate(databases):
                    db_id = db["id"]
                    title = "Senza titolo"
                    title_list = db.get("title", [])
                    if title_list:
                        title = "".join([t.get("plain_text", "") for t in title_list])
                    print(f"  {idx + 1}) {title} (ID: {db_id})")
                    
                print("\nAssocia i database ai rispettivi ruoli:")
                cal_idx = input("Quale numero corrisponde agli EVENTI/APPUNTAMENTI del calendario? ").strip()
                task_idx = input("Quale numero corrisponde ai TASK? ").strip()
                other_idx_str = input("Quali numeri corrispondono a database generici da sincronizzare (es. Clienti, Progetti, Documenti) [separati da virgola, es. 1,3,4]: ").strip()
                
                # Applica mappature
                db_ids = []
                
                if cal_idx.isdigit() and 1 <= int(cal_idx) <= len(databases):
                    cal_db_id = databases[int(cal_idx) - 1]["id"].replace("-", "")
                    settings["sources"]["notion"]["calendar_database_id"] = cal_db_id
                    db_ids.append(cal_db_id)
                    print(f"-> Calendario mappato al database: {databases[int(cal_idx) - 1].get('title', [{}])[0].get('plain_text', 'Riunioni')}")
                    
                if task_idx.isdigit() and 1 <= int(task_idx) <= len(databases):
                    task_db_id = databases[int(task_idx) - 1]["id"].replace("-", "")
                    settings["sources"]["notion"]["tasks_database_id"] = task_db_id
                    db_ids.append(task_db_id)
                    print(f"-> Task mappati al database: {databases[int(task_idx) - 1].get('title', [{}])[0].get('plain_text', 'Task')}")
                    
                if other_idx_str:
                    for part in other_idx_str.split(","):
                        part = part.strip()
                        if part.isdigit() and 1 <= int(part) <= len(databases):
                            db_id = databases[int(part) - 1]["id"].replace("-", "")
                            if db_id not in db_ids:
                                db_ids.append(db_id)
                            print(f"-> Aggiunto database generico: {databases[int(part) - 1].get('title', [{}])[0].get('plain_text', 'Generico')}")
                            
                settings["sources"]["notion"]["database_ids"] = db_ids
                settings["sources"]["notion"]["enabled"] = True
            else:
                print("Non è stato trovato alcun database condiviso. Assicurati di aver invitato la connessione 'Second brain' sulle pagine dei database in Notion.")
                settings["sources"]["notion"]["enabled"] = False
        except Exception as e:
            print(f"Errore durante la scansione di Notion: {e}")
            settings["sources"]["notion"]["enabled"] = False
    else:
        print("Integrazione Notion disabilitata o saltata.")
        settings["sources"]["notion"]["enabled"] = False

    print("\n--- 3. CONFIGURAZIONE MAIL SERVER (SMTP/IMAP) ---")
    setup_mail = input("Vuoi configurare l'invio delle email di briefing (SMTP/IMAP)? (s/n) [n]: ").strip().lower()
    if setup_mail == "s":
        smtp_server = input(f"Server SMTP [attuale: {os.getenv('SMTP_SERVER', '')}]: ").strip() or os.getenv('SMTP_SERVER', '')
        smtp_port = input(f"Porta SMTP [attuale: {os.getenv('SMTP_PORT', '465')}]: ").strip() or os.getenv('SMTP_PORT', '465')
        smtp_user = input(f"Username SMTP [attuale: {os.getenv('SMTP_USERNAME', '')}]: ").strip() or os.getenv('SMTP_USERNAME', '')
        smtp_pass = input("Password SMTP: ").strip() or os.getenv('SMTP_PASSWORD', '')
        smtp_from = input(f"Mittente Email (From) [attuale: {os.getenv('SMTP_FROM', '')}]: ").strip() or os.getenv('SMTP_FROM', '')
        smtp_to = input(f"Destinatario Briefing (To) [attuale: {os.getenv('SMTP_TO', '')}]: ").strip() or os.getenv('SMTP_TO', '')
        
        imap_server = input(f"Server IMAP [attuale: {os.getenv('IMAP_SERVER', '')}]: ").strip() or os.getenv('IMAP_SERVER', '')
        imap_port = input(f"Porta IMAP [attuale: {os.getenv('IMAP_PORT', '993')}]: ").strip() or os.getenv('IMAP_PORT', '993')
        imap_user = input(f"Username IMAP [attuale: {os.getenv('IMAP_USERNAME', '')}]: ").strip() or os.getenv('IMAP_USERNAME', '')
        imap_pass = input("Password IMAP: ").strip() or os.getenv('IMAP_PASSWORD', '')
        
        print("\nValidazione delle connessioni email in corso...")
        mail_valid = True
        try:
            print("  Test connessione SMTP...")
            if smtp_port == "465":
                smtp = smtplib.SMTP_SSL(smtp_server, int(smtp_port), timeout=10)
            else:
                smtp = smtplib.SMTP(smtp_server, int(smtp_port), timeout=10)
                if smtp_port == "587":
                    smtp.starttls()
            smtp.login(smtp_user, smtp_pass)
            smtp.quit()
            print("  -> SMTP autenticato con successo!")
        except Exception as e:
            print(f"  -> [WARNING] Connessione SMTP fallita: {e}")
            mail_valid = False
            
        try:
            print("  Test connessione IMAP...")
            if imap_port == "993":
                imap = imaplib.IMAP4_SSL(imap_server, int(imap_port), timeout=10)
            else:
                imap = imaplib.IMAP4(imap_server, int(imap_port), timeout=10)
            imap.login(imap_user, imap_pass)
            imap.logout()
            print("  -> IMAP autenticato con successo!")
        except Exception as e:
            print(f"  -> [WARNING] Connessione IMAP fallita: {e}")
            mail_valid = False
            
        if mail_valid:
            print("-> Credenziali mail validate con successo!")
        else:
            print("-> [WARNING] Alcune configurazioni email non sono validate. Saranno comunque salvate.")
            
        set_env_value("SMTP_SERVER", smtp_server)
        set_env_value("SMTP_PORT", smtp_port)
        set_env_value("SMTP_USERNAME", smtp_user)
        set_env_value("SMTP_PASSWORD", smtp_pass)
        set_env_value("SMTP_FROM", smtp_from)
        set_env_value("SMTP_TO", smtp_to)
        
        set_env_value("IMAP_SERVER", imap_server)
        set_env_value("IMAP_PORT", imap_port)
        set_env_value("IMAP_USERNAME", imap_user)
        set_env_value("IMAP_PASSWORD", imap_pass)
        
        settings["sources"]["apple_mail"]["enabled"] = True
    else:
        print("Configurazione mail saltata.")

    print("\n--- 4. CONFIGURAZIONE TELEGRAM BOT (NOTIFICHE & QUERY) ---")
    setup_tg = input("Vuoi configurare il Bot Telegram? (s/n) [n]: ").strip().lower()
    if setup_tg == "s":
        tg_token = input(f"Inserisci il token del Bot Telegram [attuale: {os.getenv('TELEGRAM_BOT_TOKEN', '')}]: ").strip() or os.getenv('TELEGRAM_BOT_TOKEN', '')
        tg_allowed = input(f"Inserisci gli ID utente abilitati (separati da virgola) [attuale: {os.getenv('TELEGRAM_ALLOWED_USERS', '')}]: ").strip() or os.getenv('TELEGRAM_ALLOWED_USERS', '')
        if tg_token:
            set_env_value("TELEGRAM_BOT_TOKEN", tg_token)
            set_env_value("TELEGRAM_ALLOWED_USERS", tg_allowed)
            print("Telegram Bot configurato.")
            
    print("\n--- 5. CONFIGURAZIONE GITHUB SYNC ---")
    setup_git = input("Vuoi configurare il push automatico su GitHub? (s/n) [n]: ").strip().lower()
    if setup_git == "s":
        git_token = input(f"Inserisci il tuo GITHUB_TOKEN [attuale: {os.getenv('GITHUB_TOKEN', '')}]: ").strip() or os.getenv('GITHUB_TOKEN', '')
        if git_token:
            set_env_value("GITHUB_TOKEN", git_token)
            print("GitHub Token configurato.")

    # Salvataggio settings.md
    save_settings(vault_path, settings)
    
    print("\n" + "="*50)
    print(" CONFIGURAZIONE COMPLETATA CON SUCCESSO!")
    print(" Le impostazioni sono state scritte in .env e settings.md")
    print("="*50 + "\n")

if __name__ == "__main__":
    run_setup_wizard()
