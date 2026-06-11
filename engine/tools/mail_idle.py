import os
import sys
import time
import asyncio
from imapclient import IMAPClient
from engine.utils.markdown import load_settings
from engine.tools.vault_tools import get_vault_path

async def run_idle_for_account(server_host, port, username, password, folder, callback):
    print(f"[IMAP-IDLE] Avvio listener per {username} su {server_host}:{port}...", flush=True)
    
    while True:
        try:
            await asyncio.to_thread(
                _sync_idle_loop, server_host, port, username, password, folder, callback
            )
        except asyncio.CancelledError:
            print(f"[IMAP-IDLE] Listener cancellato per {username}.", flush=True)
            break
        except Exception as e:
            print(f"[IMAP-IDLE] Errore listener per {username}: {e}. Riavvio tra 10 secondi...", flush=True)
            await asyncio.sleep(10)

def _sync_idle_loop(server_host, port, username, password, folder, callback):
    while True:
        try:
            print(f"[IMAP-IDLE] Connessione a {server_host}:{port} ({username})...", flush=True)
            use_ssl = int(port) == 993
            
            import ssl
            ssl_context = ssl._create_unverified_context()
            client = IMAPClient(server_host, port=int(port), ssl=use_ssl, ssl_context=ssl_context if use_ssl else None, timeout=30)
            client.login(username, password)
            client.select_folder(folder)
            
            print(f"[IMAP-IDLE] Connesso e in ascolto su {folder} per {username}.", flush=True)
            
            # Rinfresca IDLE ogni 10 minuti per evitare disconnessioni da parte del server
            refresh_interval_secs = 600
            
            while True:
                client.idle()
                try:
                    responses = client.idle_check(timeout=refresh_interval_secs)
                    client.idle_done()
                    
                    if responses:
                        print(f"[IMAP-IDLE] Notifica ricevuta da {username}: {responses}", flush=True)
                        callback()
                except Exception as idle_err:
                    try:
                        client.idle_done()
                    except Exception:
                        pass
                    raise idle_err
                    
        except Exception as conn_err:
            print(f"[IMAP-IDLE] Connessione persa per {username}: {conn_err}. Riprovo tra 10 secondi...", flush=True)
            time.sleep(10)
            break

async def start_imap_idle_listeners(ingestion_manager):
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    
    mail_settings = settings.get("sources", {}).get("apple_mail", {})
    if not mail_settings.get("enabled", False):
        print("[IMAP-IDLE] Sorgente Mail disabilitata nelle impostazioni. Listener IDLE non avviato.", flush=True)
        return []
        
    accounts = []
    
    # Verifica account multipli in settings.md
    configured_accounts = settings.get("sources", {}).get("mail_accounts", [])
    if isinstance(configured_accounts, list) and len(configured_accounts) > 0:
        for acc in configured_accounts:
            if acc.get("enabled", False):
                server = acc.get("server")
                port = int(acc.get("port", "993"))
                username = acc.get("username")
                mailbox = acc.get("mailbox", "INBOX")
                pass_env = acc.get("password_env")
                
                password = os.getenv(pass_env) if pass_env else None
                if server and username and password:
                    accounts.append({
                        "server": server,
                        "port": port,
                        "username": username,
                        "password": password,
                        "mailbox": mailbox
                    })
                    
    # Fallback all'account singolo nel file .env
    if not accounts:
        imap_server = os.getenv("IMAP_SERVER")
        imap_port = os.getenv("IMAP_PORT", "993")
        imap_username = os.getenv("IMAP_USERNAME")
        imap_password = os.getenv("IMAP_PASSWORD")
        imap_mailbox = os.getenv("IMAP_MAILBOX", mail_settings.get("mailbox", "SecondBrain"))
        
        if imap_server and imap_username and imap_password:
            accounts.append({
                "server": imap_server,
                "port": imap_port,
                "username": imap_username,
                "password": imap_password,
                "mailbox": imap_mailbox
            })
            
    if not accounts:
        print("[IMAP-IDLE] Nessun account IMAP configurato per il listener IDLE.", flush=True)
        return []
        
    loop = asyncio.get_running_loop()
    
    def on_mail_notification():
        print("[IMAP-IDLE] Rilevata ricezione di nuove e-mail. Avvio sync ed ingestion...", flush=True)
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(trigger_sync_and_ingestion(ingestion_manager))
        )
        
    tasks = []
    for acc in accounts:
        task = asyncio.create_task(
            run_idle_for_account(
                acc["server"],
                acc["port"],
                acc["username"],
                acc["password"],
                acc["mailbox"],
                on_mail_notification
            )
        )
        tasks.append(task)
        
    return tasks

async def trigger_sync_and_ingestion(ingestion_manager):
    if ingestion_manager.is_running():
        print("[IMAP-IDLE] Ingestione già in esecuzione, trigger posticipato.", flush=True)
        return
        
    print("[IMAP-IDLE] Avvio dell'ingestione per la fonte 'mail'...", flush=True)
    await ingestion_manager.start(source="mail")
