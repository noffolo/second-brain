import os
import sys
import subprocess
import re
import shutil
import time
import imaplib
import email
from email.header import decode_header
from email.policy import default
from engine.utils.markdown import load_settings
from engine.tools.drive_tools import extract_pdf_text, extract_docx_text

def get_vault_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def decode_mime_header(header_value: str) -> str:
    if not header_value:
        return ""
    decoded_parts = decode_header(header_value)
    result = []
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(encoding or "utf-8", errors="ignore"))
            except Exception:
                result.append(part.decode("latin1", errors="ignore"))
        else:
            result.append(str(part))
    return "".join(result)

def imap_sync_to_raw() -> int:
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    
    mail_settings = settings.get("sources", {}).get("apple_mail", {})
    if not mail_settings.get("enabled", False):
        print("Sorgente Mail disabilitata nelle impostazioni.")
        return 0
        
    # Costruiamo la lista degli account da scansionare
    accounts_to_sync = []
    
    # Controlliamo se c'è una lista configurata in settings.md
    configured_accounts = settings.get("sources", {}).get("mail_accounts", [])
    if isinstance(configured_accounts, list) and len(configured_accounts) > 0:
        for acc in configured_accounts:
            if acc.get("enabled", False):
                server = acc.get("server")
                port = str(acc.get("port", "993"))
                username = acc.get("username")
                mailbox = acc.get("mailbox", "INBOX")
                pass_env = acc.get("password_env")
                
                password = os.getenv(pass_env) if pass_env else None
                if server and username and password:
                    accounts_to_sync.append({
                        "server": server,
                        "port": port,
                        "username": username,
                        "password": password,
                        "mailbox": mailbox
                    })
    
    # Se non c'è una lista o nessun account abilitato, ricadiamo sul singolo account del .env
    if not accounts_to_sync:
        imap_server = os.getenv("IMAP_SERVER")
        imap_port = os.getenv("IMAP_PORT", "993")
        imap_username = os.getenv("IMAP_USERNAME")
        imap_password = os.getenv("IMAP_PASSWORD")
        imap_mailbox = os.getenv("IMAP_MAILBOX", mail_settings.get("mailbox", "SecondBrain"))
        
        if imap_server and imap_username and imap_password:
            accounts_to_sync.append({
                "server": imap_server,
                "port": imap_port,
                "username": imap_username,
                "password": imap_password,
                "mailbox": imap_mailbox
            })
            
    if not accounts_to_sync:
        print("Nessun account IMAP configurato in settings.md o in .env.")
        return 0
        
    attachments_dir = os.path.abspath(os.path.join(vault_path, mail_settings.get("attachments_dir", "raw/mail_attachments")))
    os.makedirs(attachments_dir, exist_ok=True)
    
    raw_mail_dir = os.path.abspath(os.path.join(vault_path, "raw", "mail"))
    os.makedirs(raw_mail_dir, exist_ok=True)
    
    total_new_synced = 0
    
    for acc in accounts_to_sync:
        server = acc["server"]
        port = acc["port"]
        username = acc["username"]
        password = acc["password"]
        mailbox = acc["mailbox"]
        
        print(f"Avvio sincronizzazione e-mail via IMAP da {server} (utente: {username}, mailbox: {mailbox})...")
        
        try:
            # Connessione SSL
            import ssl
            ssl_context = ssl._create_unverified_context()
            mail_client = imaplib.IMAP4_SSL(server, int(port), ssl_context=ssl_context)
            mail_client.login(username, password)
            
            # Seleziona la mailbox
            status, data = mail_client.select(mailbox)
            if status != "OK":
                print(f"Mailbox '{mailbox}' non trovata per {username}. Ricado su INBOX.")
                status, data = mail_client.select("INBOX")
                if status != "OK":
                    print(f"Impossibile selezionare INBOX per {username}.")
                    mail_client.logout()
                    continue
            
            # Calcolo data limite se days_back è specificato
            days_back = mail_settings.get("days_back", 0)
            if days_back > 0:
                import datetime
                date_limit = datetime.date.today() - datetime.timedelta(days=days_back)
                months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                imap_date_str = f"{date_limit.day:02d}-{months[date_limit.month - 1]}-{date_limit.year}"
                print(f"Ricerca e-mail a partire dal {imap_date_str} (ultimi {days_back} giorni)...")
                status, messages = mail_client.search(None, f"SINCE {imap_date_str}")
            else:
                status, messages = mail_client.search(None, "ALL")

            if status != "OK" or not messages[0]:
                print(f"Nessun messaggio trovato nella mailbox per {username}.")
                mail_client.logout()
                continue
                
            message_ids = messages[0].split()
            print(f"Trovate {len(message_ids)} email totali sul server IMAP per {username} con le impostazioni correnti.")
            
            message_ids.reverse()
            
            exclude_senders = mail_settings.get("exclude_senders", [])
            exclude_domains = mail_settings.get("exclude_domains", [])
            exclude_subjects = mail_settings.get("exclude_subjects", [])
            
            # Carica in memoria gli UID delle email già scaricate per fare O(1) lookup
            clean_user = re.sub(r'[^a-zA-Z0-9]', '_', username)
            existing_uids = set()
            if os.path.exists(raw_mail_dir):
                for name in os.listdir(raw_mail_dir):
                    if name.startswith(f"imap_{clean_user}_") and name.endswith(".md"):
                        prefix = f"imap_{clean_user}_"
                        uid = name[len(prefix):-3]
                        existing_uids.add(uid)
            
            missing_uids = []
            for msg_uid_bytes in message_ids:
                msg_uid = msg_uid_bytes.decode()
                if msg_uid not in existing_uids:
                    missing_uids.append(msg_uid)
                    
            print(f"Trovate {len(missing_uids)} email mancanti da analizzare su {len(message_ids)} totali.")
            
            new_synced = 0
            
            # Scarica gli header in lotti (batch)
            batch_size = 100
            for start_idx in range(0, len(missing_uids), batch_size):
                batch = missing_uids[start_idx:start_idx + batch_size]
                batch_str = ",".join(batch)
                
                try:
                    status, fetch_data = mail_client.uid('fetch', batch_str, '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])')
                    if status != "OK" or not fetch_data:
                        continue
                except Exception as batch_err:
                    print(f"Errore nel fetch degli header del lotto da {start_idx}: {batch_err}")
                    continue
                
                headers_by_uid = {}
                current_uid = None
                
                for part in fetch_data:
                    if isinstance(part, tuple):
                        preamble = part[0].decode("utf-8", errors="ignore")
                        uid_match = re.search(r'\bUID\s+(\d+)\b', preamble, re.IGNORECASE)
                        if uid_match:
                            current_uid = uid_match.group(1)
                            header_content = part[1].decode("utf-8", errors="ignore")
                            headers_by_uid[current_uid] = header_content
                
                for msg_uid in batch:
                    header_text = headers_by_uid.get(msg_uid)
                    if not header_text:
                        continue
                    
                    subject = ""
                    sender = ""
                    date_str = ""
                    
                    for line in header_text.splitlines():
                        if line.lower().startswith("subject:"):
                            subject = decode_mime_header(line[8:].strip())
                        elif line.lower().startswith("from:"):
                            sender = decode_mime_header(line[5:].strip())
                        elif line.lower().startswith("date:"):
                            date_str = line[5:].strip()
                            
                    sender_lower = sender.lower()
                    subject_lower = subject.lower()
                    
                    if any(exc in sender_lower for exc in exclude_senders) or \
                       any(dom in sender_lower for dom in exclude_domains) or \
                       any(subj in subject_lower for subj in exclude_subjects):
                        # Scrivi comunque un file segnaposto per evitare di riscaricarla la prossima volta
                        filepath = os.path.join(raw_mail_dir, f"imap_{clean_user}_{msg_uid}.md")
                        clean_sender = sender.replace('"', '\\"')
                        clean_subject = subject.replace('"', '\\"')
                        md_content = f"""---
type: email
message_id: "imap_{clean_user}_{msg_uid}"
sender: "{clean_sender}"
subject: "{clean_subject}"
date: "{date_str}"
---

# {subject}

**Da**: {sender}  
**Data**: {date_str}  

## Contenuto del Messaggio

[Corpo non scaricato - email di servizio/non rilevante]
"""
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write(md_content)
                        continue
                    
                    filepath = os.path.join(raw_mail_dir, f"imap_{clean_user}_{msg_uid}.md")
                    
                    try:
                        status, msg_data = mail_client.uid('fetch', msg_uid, '(BODY.PEEK[])')
                        if status != "OK" or not msg_data:
                            continue
                    except Exception as fetch_body_err:
                        print(f"Errore nel fetch del corpo per UID {msg_uid}: {fetch_body_err}")
                        continue
                        
                    raw_email_content = None
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            raw_email_content = response_part[1]
                            break
                            
                    if not raw_email_content:
                        continue
                        
                    msg = email.message_from_bytes(raw_email_content, policy=default)
                    
                    body_text = ""
                    attachments_sections = []
                    
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))
                        
                        if "attachment" in content_disposition:
                            filename_att = part.get_filename()
                            if filename_att:
                                filename_att = decode_mime_header(filename_att)
                                _, ext = os.path.splitext(filename_att.lower())
                                save_att = False
                                if ext in [".csv", ".xlsx", ".xls", ".pdf", ".docx", ".doc", ".txt", ".md"]:
                                    att_name_lower = filename_att.lower()
                                    keywords_att = [
                                        "iscritti", "report", "ade", "adm", "usb", "mef", 
                                        "partecipanti", "anagrafica", "corso", "soci", 
                                        "paypal", "banca", "estratto", "tessera", "donazione"
                                    ]
                                    if any(k in att_name_lower for k in keywords_att) or ext == ".pdf":
                                        save_att = True
                                        
                                if save_att:
                                    att_filename = f"imap_{clean_user}_{msg_uid}_{filename_att}"
                                    att_filepath = os.path.join(attachments_dir, att_filename)
                                    
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        with open(att_filepath, "wb") as f:
                                            f.write(payload)
                                            
                                        extracted_text = ""
                                        if ext == ".pdf":
                                            extracted_text = extract_pdf_text(att_filepath)
                                        elif ext in [".docx", ".doc"]:
                                            extracted_text = extract_docx_text(att_filepath)
                                        elif ext in [".txt", ".md"]:
                                            try:
                                                extracted_text = payload.decode("utf-8", errors="ignore")
                                            except Exception as e:
                                                extracted_text = f"[Errore lettura file di testo: {e}]"
                                                
                                        if extracted_text:
                                            att_section = f"\n---\n### Allegato Estratto: {filename_att}\n\n{extracted_text}\n"
                                            attachments_sections.append(att_section)
                        
                        elif content_type == "text/plain" and not body_text:
                            payload = part.get_payload(decode=True)
                            if payload:
                                body_text = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                        elif content_type == "text/html" and not body_text:
                            payload = part.get_payload(decode=True)
                            if payload:
                                html_content = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                                body_text = extract_body_from_mime(html_content)
                                
                    if not body_text:
                        try:
                            body = msg.get_body(preferencelist=('plain', 'html'))
                            if body:
                                body_text = body.get_content()
                        except Exception:
                            body_text = "[Nessun contenuto di testo estraibile]"
                            
                    clean_sender = sender.replace('"', '\\"')
                    clean_subject = subject.replace('"', '\\"')
                    
                    md_content = f"""---
type: email
message_id: "imap_{clean_user}_{msg_uid}"
sender: "{clean_sender}"
subject: "{clean_subject}"
date: "{date_str}"
---

# {subject}

**Da**: {sender}  
**Data**: {date_str}  

## Contenuto del Messaggio

{body_text.strip()}
"""

                    if attachments_sections:
                        md_content += "\n## Allegati ed Estratti Contenuto\n"
                        for section in attachments_sections:
                            md_content += section
                            
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(md_content)
                        
                    new_synced += 1
            
            mail_client.logout()
            print(f"Sincronizzazione completata per {username}. Scaricate {new_synced} nuove email rilevanti.")
            total_new_synced += new_synced
        except Exception as e:
            print(f"Errore durante la sincronizzazione dell'account {username}: {e}")
            
    return total_new_synced


def run_applescript(script: str) -> str:
    """
    Esegue uno script AppleScript in modo sicuro passando la stringa tramite stdin a osascript.
    """
    process = subprocess.Popen(
        ['osascript'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8"
    )
    stdout, stderr = process.communicate(input=script)
    if process.returncode != 0:
        raise RuntimeError(f"AppleScript fallito: {stderr}")
    return stdout

def is_special_mailbox(mb_path: str) -> bool:
    """
    Ritorna True se il percorso della mailbox contiene parole chiave speciali/di servizio.
    """
    mb_lower = mb_path.lower()
    special_keywords = [
        "trash", "cestino", "deleted", "eliminati", "eliminate", 
        "junk", "indesiderata", "spam", "draft", "bozze", 
        "template", "sendlater", "outbox"
    ]
    return any(keyword in mb_lower for keyword in special_keywords)

def build_mailbox_ref(mailbox_path: str, account_name: str = None) -> str:
    """
    Costruisce l'espressione AppleScript per referenziare una mailbox (anche annidata).
    """
    parts = mailbox_path.split("/")
    ref = f'mailbox "{parts[-1]}"'
    for part in reversed(parts[:-1]):
        ref += f' of mailbox "{part}"'
    if account_name:
        ref += f' of account "{account_name}"'
    return ref

def extract_body_from_mime(mime_text: str) -> str:
    import email
    from email.policy import default
    import html
    try:
        msg = email.message_from_string(mime_text, policy=default)
        body = msg.get_body(preferencelist=('plain', 'html'))
        if body:
            content = body.get_content()
            if body.get_content_type() == 'text/html':
                content = re.sub(r'<script.*?>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
                content = re.sub(r'<style.*?>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
                content = re.sub(r'<br\s*/?>', '\n', content, flags=re.IGNORECASE)
                content = re.sub(r'</p>', '\n\n', content, flags=re.IGNORECASE)
                content = re.sub(r'</div>', '\n', content, flags=re.IGNORECASE)
                content = re.sub(r'<[^>]+>', '', content)
                content = html.unescape(content)
                content = re.sub(r'\n\s*\n+', '\n\n', content)
            return content.strip()
    except Exception as e:
        return f"[Errore parsing MIME: {e}]"
    return mime_text

def parse_and_write_messages(raw_output: str, raw_mail_dir: str, attachments_dir: str, metadata_lookup: dict = None) -> int:
    """
    Esegue il parsing dei blocchi email scaricati da AppleScript e scrive i relativi file markdown.
    """
    msg_blocks = re.findall(r"\[\[MSG_START\]\]\n(.*?)\n\[\[MSG_END\]\]", raw_output, re.DOTALL)
    written_count = 0
    
    for block in msg_blocks:
        if "ERROR: " in block:
            print(f"Avviso: errore riscontrato durante lo scaricamento di un messaggio: {block.strip()}")
            continue
            
        try:
            meta_part, body_part = block.split("[[BODY_START]]\n", 1)
        except ValueError:
            continue
            
        # Estrazione chiavi metadati
        msg_id = ""
        sender = ""
        subject = ""
        date_str = ""
        attachments_str = ""
        
        for line in meta_part.splitlines():
            if line.startswith("ID: "):
                msg_id = line[4:].strip()
            elif line.startswith("Sender: "):
                sender = line[8:].strip()
            elif line.startswith("Subject: "):
                subject = line[9:].strip()
            elif line.startswith("Date: "):
                date_str = line[6:].strip()
            elif line.startswith("Attachments: "):
                attachments_str = line[13:].strip()
                
        if not msg_id:
            continue
            
        if metadata_lookup and msg_id:
            try:
                meta_item = metadata_lookup.get(int(msg_id))
                if meta_item:
                    sender = meta_item.get("sender", sender)
                    subject = meta_item.get("subject", subject)
                    date_str = meta_item.get("date", date_str)
            except Exception:
                pass
            
        filename = f"{msg_id}.md"
        filepath = os.path.join(raw_mail_dir, filename)
        
        # Gestione allegati ed estrazione testo
        attachments_sections = []
        if attachments_str:
            attachment_names = [a.strip() for a in attachments_str.split(",") if a.strip()]
            for att_name in attachment_names:
                att_filename = f"{msg_id}_{att_name}"
                att_filepath = os.path.join(attachments_dir, att_filename)
                
                if os.path.exists(att_filepath):
                    _, ext = os.path.splitext(att_name.lower())
                    extracted_text = ""
                    
                    if ext == ".pdf":
                        extracted_text = extract_pdf_text(att_filepath)
                    elif ext in [".docx", ".doc"]:
                        extracted_text = extract_docx_text(att_filepath)
                    elif ext in [".txt", ".md"]:
                        try:
                            with open(att_filepath, "r", encoding="utf-8", errors="ignore") as f:
                                extracted_text = f.read()
                        except Exception as e:
                            extracted_text = f"[Errore lettura file di testo: {e}]"
                            
                    if extracted_text:
                        att_section = f"\n---\n### Allegato Estratto: {att_name}\n\n{extracted_text}\n"
                        attachments_sections.append(att_section)
                        
        clean_sender = sender.replace('"', '\\"')
        clean_subject = subject.replace('"', '\\"')
        
        if body_part.strip().startswith("[Corpo non scaricato"):
            body_text = body_part
        else:
            body_text = extract_body_from_mime(body_part)
            
        md_content = f"""---
type: email
message_id: "{msg_id}"
sender: "{clean_sender}"
subject: "{clean_subject}"
date: "{date_str}"
---

# {subject}

**Da**: {sender}  
**Data**: {date_str}  

## Contenuto del Messaggio

{body_text}
"""

        if attachments_sections:
            md_content += "\n## Allegati ed Estratti Contenuto\n"
            for section in attachments_sections:
                md_content += section
                
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_content)
            
        written_count += 1
        
    return written_count

def apple_mail_sync_to_raw() -> int:
    """
    Sincronizza le email. Se IMAP è configurato nel file .env usa il server mail direttamente, altrimenti ricade su Apple Mail (macOS).
    """
    if os.getenv("IMAP_SERVER"):
        return imap_sync_to_raw()
        
    if sys.platform != "darwin":
        print("Sorgente Mail ignorata: supportata solo su macOS oppure tramite server IMAP configurato in .env.")
        return 0
        
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    
    mail_settings = settings.get("sources", {}).get("apple_mail", {})
    if not mail_settings.get("enabled", False):
        print("Sorgente Apple Mail disabilitata nelle impostazioni.")
        return 0
        
    sync_all_accounts = mail_settings.get("sync_all_accounts", False)
    mailbox_name = mail_settings.get("mailbox", "SecondBrain")
    days_back = mail_settings.get("days_back", 0)
    
    attachments_dir = os.path.abspath(os.path.join(vault_path, mail_settings.get("attachments_dir", "raw/mail_attachments")))
    os.makedirs(attachments_dir, exist_ok=True)
    
    raw_mail_dir = os.path.abspath(os.path.join(vault_path, "raw", "mail"))
    os.makedirs(raw_mail_dir, exist_ok=True)
    
    print(f"Interrogazione e mappatura Apple Mail (sync_all_accounts={sync_all_accounts}, days_back={days_back})...")
    
    # 1. Recupero la lista di mailboxes da sincronizzare
    mailboxes_to_sync = []
    
    if sync_all_accounts:
        try:
            acc_names_output = run_applescript('tell application "Mail" to get name of every account')
            all_acc_names = [x.strip() for x in acc_names_output.split(",") if x.strip()]
            
            prefix = os.getenv("APPLE_MAIL_ACCOUNT_PREFIX", mail_settings.get("account_prefix", ""))
            if prefix:
                matched_acc_names = [x for x in all_acc_names if x.startswith(prefix)]
            else:
                matched_acc_names = all_acc_names
        except Exception as e:
            print(f"Errore nel recupero dei nomi degli account: {e}")
            return 0
            
        if not matched_acc_names:
            print("Nessun account e-mail corrispondente trovato.")
            return 0
            
        acc_list_applescript = "{" + ", ".join(f'"{name}"' for name in matched_acc_names) + "}"
        list_mbs_script = f"""
        set accNames to {acc_list_applescript}
        set outText to ""
        repeat with i from 1 to count of accNames
            set accNameStr to item i of accNames
            tell application "Mail"
                try
                    set mbNames to name of every mailbox of account accNameStr
                    repeat with j from 1 to count of mbNames
                        set mbName to item j of mbNames
                        set outText to outText & accNameStr & "||" & mbName & "\\n"
                    end repeat
                end try
            end tell
        end repeat
        return outText
        """
        try:
            mbs_output = run_applescript(list_mbs_script)
            for line in mbs_output.splitlines():
                if "||" in line:
                    acc, path = line.split("||", 1)
                    if not is_special_mailbox(path):
                        mailboxes_to_sync.append((acc, path))
        except Exception as e:
            print(f"Errore nella scansione delle mailbox: {e}")
            return 0
    else:
        # Trova la mailbox specifica a livello globale o di account
        find_mb_script = f"""
        tell application "Mail"
            repeat with acc in accounts
                if exists mailbox "{mailbox_name}" of acc then
                    return name of acc & "||{mailbox_name}"
                end if
            end repeat
            if exists mailbox "{mailbox_name}" then
                return "||{mailbox_name}"
            end if
            return "ERROR: Mailbox '{mailbox_name}' non trovata."
        end tell
        """
        try:
            find_res = run_applescript(find_mb_script).strip()
            if find_res.startswith("ERROR:"):
                print(find_res)
                return 0
            acc, path = find_res.split("||", 1)
            mailboxes_to_sync.append((acc if acc else None, path))
        except Exception as e:
            print(f"Errore nella ricerca della mailbox '{mailbox_name}': {e}")
            return 0
            
    print(f"Trovate {len(mailboxes_to_sync)} mailbox da sincronizzare.")
    total_new_synced = 0
    
    # 2. Per ogni mailbox, esegui sincronizzazione a 3 fasi
    for acc_name, mb_path in mailboxes_to_sync:
        acc_label = acc_name if acc_name else "Locale"
        print(f"\nSincronizzazione mailbox: [{acc_label}] -> '{mb_path}'")
        
        mb_ref = build_mailbox_ref(mb_path, acc_name)
        
        # FASE 1: Recupero vettoriale rapido di tutti i metadati
        try:
            start_f1 = time.time()
            remote_ids = []
            senders = []
            subjects = []
            dates = []
            
            # Recuperiamo prima il conteggio totale dei messaggi (operazione istantanea)
            count_script = f"""
            tell application "Mail"
                return count of messages of {mb_ref}
            end tell
            """
            total_count = int(run_applescript(count_script).strip())
            
            if total_count > 0:
                # Recupero vettoriale di tutti i metadati
                def get_vector_prop(prop_name):
                    as_script = f"""
                    tell application "Mail"
                        set mb to {mb_ref}
                        set valList to {prop_name} of messages of mb
                        set oldDelims to AppleScript's text item delimiters
                        set AppleScript's text item delimiters to "<||>"
                        set outStr to valList as string
                        set AppleScript's text item delimiters to oldDelims
                        return outStr
                    end tell
                    """
                    return run_applescript(as_script).split("<||>")

                print("  - Fase 1 (Mappatura Vettoriale): Recupero ID, mittenti, oggetti e date...")
                remote_ids_str = get_vector_prop("id")
                remote_ids = [int(x) for x in remote_ids_str if x.strip()]
                
                total_count = len(remote_ids)
                if total_count > 0:
                    senders = get_vector_prop("sender")
                    subjects = get_vector_prop("subject")
                    dates = get_vector_prop("date received")
                    
                    min_len = min(len(remote_ids), len(senders), len(subjects), len(dates))
                    remote_ids = remote_ids[:min_len]
                    senders = senders[:min_len]
                    subjects = subjects[:min_len]
                    dates = dates[:min_len]
                    
                    # Se days_back > 0, eseguiamo la ricerca binaria per limitare l'intervallo
                    if days_back > 0:
                        sort_dir = "normal"
                        if total_count > 5:
                            sort_script = f"""
                            tell application "Mail"
                                set mb to {mb_ref}
                                set totalCount to {total_count}
                                try
                                    set lastDate to date received of message totalCount of mb
                                    set prevDate to date received of message (totalCount - 4) of mb
                                    if prevDate is greater than lastDate then
                                        return "reversed"
                                    else
                                        return "normal"
                                    end if
                                on error
                                    return "normal"
                                end try
                            end tell
                            """
                            sort_dir = run_applescript(sort_script).strip()
                        
                        k = None
                        idx = total_count if sort_dir == "normal" else 1
                        step = 200
                        
                        # Esegui ricerca binaria/salto per data
                        if sort_dir == "normal":
                            while idx > 1:
                                check_idx = max(1, idx - step)
                                check_script = f"""
                                tell application "Mail"
                                    set mb to {mb_ref}
                                    set dateLimit to (current date) - ({days_back} * days)
                                    try
                                        set msgDate to date received of message {check_idx} of mb
                                        if msgDate is greater than dateLimit then
                                            return "newer"
                                        else
                                            return "older"
                                        end if
                                    on error
                                        return "error"
                                    end try
                                end tell
                                """
                                res = run_applescript(check_script).strip()
                                if res == "older":
                                    low = check_idx
                                    high = idx
                                    while low <= high:
                                        mid = (low + high) // 2
                                        mid_script = f"""
                                        tell application "Mail"
                                            set mb to {mb_ref}
                                            set dateLimit to (current date) - ({days_back} * days)
                                            try
                                                set msgDate to date received of message {mid} of mb
                                                if msgDate is greater than dateLimit then
                                                    return "newer"
                                                else
                                                    return "older"
                                                end if
                                            on error
                                                return "error"
                                            end try
                                        end tell
                                        """
                                        mid_res = run_applescript(mid_script).strip()
                                        if mid_res == "newer":
                                            k = mid
                                            high = mid - 1
                                        else:
                                            low = mid + 1
                                    break
                                else:
                                    if check_idx == 1:
                                        k = 1
                                        break
                                    idx = check_idx
                                    step = min(5000, step * 2)
                            
                            if k is None and total_count > 0:
                                check_last_script = f"""
                                tell application "Mail"
                                    set mb to {mb_ref}
                                    set dateLimit to (current date) - ({days_back} * days)
                                    try
                                        set msgDate to date received of message {total_count} of mb
                                        if msgDate is greater than dateLimit then
                                            return "newer"
                                        else
                                            return "older"
                                        end if
                                    on error
                                        return "older"
                                    end try
                                end tell
                                """
                                if run_applescript(check_last_script).strip() == "newer":
                                    k = 1
                                    
                            if k is not None:
                                start_idx, end_idx = k, total_count
                                remote_ids = remote_ids[start_idx-1:end_idx]
                                senders = senders[start_idx-1:end_idx]
                                subjects = subjects[start_idx-1:end_idx]
                                dates = dates[start_idx-1:end_idx]
                        else:
                            # reversed logic
                            while idx < total_count:
                                check_idx = min(total_count, idx + step)
                                check_script = f"""
                                tell application "Mail"
                                    set mb to {mb_ref}
                                    set dateLimit to (current date) - ({days_back} * days)
                                    try
                                        set msgDate to date received of message {check_idx} of mb
                                        if msgDate is greater than dateLimit then
                                            return "newer"
                                        else
                                            return "older"
                                        end if
                                    on error
                                        return "error"
                                    end try
                                end tell
                                """
                                res = run_applescript(check_script).strip()
                                if res == "older":
                                    low = idx
                                    high = check_idx
                                    while low <= high:
                                        mid = (low + high) // 2
                                        mid_script = f"""
                                        tell application "Mail"
                                            set mb to {mb_ref}
                                            set dateLimit to (current date) - ({days_back} * days)
                                            try
                                                set msgDate to date received of message {mid} of mb
                                                if msgDate is greater than dateLimit then
                                                    return "newer"
                                                else
                                                    return "older"
                                                end if
                                            on error
                                                return "error"
                                            end try
                                        end tell
                                        """
                                        mid_res = run_applescript(mid_script).strip()
                                        if mid_res == "newer":
                                            k = mid
                                            low = mid + 1
                                        else:
                                            high = mid - 1
                                    break
                                else:
                                    if check_idx == total_count:
                                        k = total_count
                                        break
                                    idx = check_idx
                                    step = min(5000, step * 2)
                                    
                            if k is None and total_count > 0:
                                check_first_script = f"""
                                tell application "Mail"
                                    set mb to {mb_ref}
                                    set dateLimit to (current date) - ({days_back} * days)
                                    try
                                        set msgDate to date received of message 1 of mb
                                        if msgDate is greater than dateLimit then
                                            return "newer"
                                        else
                                            return "older"
                                        end if
                                    on error
                                        return "older"
                                    end try
                                end tell
                                """
                                if run_applescript(check_first_script).strip() == "newer":
                                    k = total_count
                                    
                            if k is not None:
                                start_idx, end_idx = 1, k
                                remote_ids = remote_ids[start_idx-1:end_idx]
                                senders = senders[start_idx-1:end_idx]
                                subjects = subjects[start_idx-1:end_idx]
                                dates = dates[start_idx-1:end_idx]

            min_len = len(remote_ids)
            f1_time = time.time() - start_f1
            print(f"  - Fase 1 (Mappatura): Rilevate {min_len} email (totale mailbox: {total_count}) in {f1_time:.2f}s.")
        except Exception as e:
            print(f"  - Errore nel recupero degli ID per la mailbox {mb_path}: {e}")
            continue
            
        if not remote_ids:
            continue
            
        # FASE 2: Filtro differenziale locale in Python + Scrittura immediata dei messaggi non rilevanti
        missing_items = []  # list of dicts
        
        # Pattern con confini di parola per evitare falsi positivi
        keywords_pattern = re.compile(
            r'\b(?:'
            r'iscritti|iscritt[oa]|iscrizione|iscrizioni|'
            r'report|'
            r'ade|adm|usb|mef|'
            r'partecipanti|partecipante|partecipazione|partecipazioni|'
            r'anagrafica|'
            r'corso|corsi|'
            r'soci|socio|socia|'
            r'paypal|'
            r'banca|'
            r'estratto|'
            r'registrazione|registrazioni|'
            r'conferma|'
            r'pagamento|pagamenti|'
            r'donazione|donazioni|'
            r'tesseramento|'
            r'bonifico|bonifici|'
            r'ricevuta|ricevute|'
            r'adesione|adesioni'
            r')\b',
            re.IGNORECASE
        )
        
        exclude_senders = [
            "amazon.it", "amazon.com", "instagram.com", "facebook.com", "google.com",
            "linkedin.com", "dropbox.com", "zoom.us", "github.com", "pinterest.com",
            "spotify.com", "netflix.com", "apple.com", "icloud.com"
        ]
        
        non_relevant_written = 0
        
        print("  - Fase 2 (Filtro): Identificazione email mancanti...")
        for i in range(min_len):
            msg_id = remote_ids[i]
            sender = senders[i]
            subject = subjects[i]
            date_str = dates[i]
            
            filepath = os.path.join(raw_mail_dir, f"{msg_id}.md")
            if not os.path.exists(filepath):
                sender_lower = sender.lower()
                is_excluded_sender = any(dom in sender_lower for dom in exclude_senders)
                
                is_relevant = False
                if not is_excluded_sender:
                    is_relevant = True
                
                 # Pattern per le email di cui scaricare SEMPRE il corpo (es. iscrizioni, registrazioni, paypal)
                strict_body_pattern = re.compile(
                    r'\b(?:'
                    r'iscrizione|iscrizioni|iscritt[oa]|'
                    r'registrazione|registrazioni|'
                    r'adesione|adesioni|'
                    r'tesseramento|'
                    r'paypal|'
                    r'donazione|donazioni'
                    r')\b',
                    re.IGNORECASE
                )
                
                if is_relevant:
                    is_strict = True
                    # Keep index as i + 1 (1-based index in Mail.app mailbox)
                    missing_items.append({
                        "index": i + 1,
                        "id": msg_id,
                        "sender": sender,
                        "subject": subject,
                        "date": date_str,
                        "strict": is_strict
                    })
                else:
                    clean_sender = sender.replace('"', '\\"')
                    clean_subject = subject.replace('"', '\\"')
                    md_content = f"""---
type: email
message_id: "{msg_id}"
sender: "{clean_sender}"
subject: "{clean_subject}"
date: "{date_str}"
---

# {subject}

**Da**: {sender}  
**Data**: {date_str}  

## Contenuto del Messaggio

[Corpo non scaricato - email di servizio/non rilevante]
"""
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(md_content)
                    non_relevant_written += 1
                    
        total_missing = len(missing_items)
        if total_missing == 0:
            print(f"  - Sincronizzazione locale completata: Scritte {non_relevant_written} email non rilevanti. 0 nuove email rilevanti.")
            continue
            
        print(f"  - Fase 2 completata: Scritte {non_relevant_written} email non rilevanti. Trovate {total_missing} email rilevanti da scaricare.")
        
        # FASE 3: Scaricamento lotti (chunking) dei dettagli dei messaggi rilevanti
        batch_size = 20
        mailbox_synced = 0
        metadata_lookup = {item["id"]: item for item in missing_items}
        
        for start_chunk in range(0, total_missing, batch_size):
            chunk = missing_items[start_chunk:start_chunk + batch_size]
            batch_indices = [item["index"] for item in chunk]
            batch_ids = [item["id"] for item in chunk]
            batch_stricts = ["true" if item["strict"] else "false" for item in chunk]
            
            indices_str = "{" + ", ".join(map(str, batch_indices)) + "}"
            ids_str = "{" + ", ".join(map(str, batch_ids)) + "}"
            stricts_str = "{" + ", ".join(batch_stricts) + "}"
            
            fetch_details_script = f"""
            set destFolder to "{attachments_dir}"
            tell application "Mail"
                with timeout of 600 seconds
                    set mb to {mb_ref}
                    set targetIndices to {indices_str}
                    set targetIds to {ids_str}
                    set targetStricts to {stricts_str}
                    set outText to ""
                    
                    repeat with i from 1 to count of targetIndices
                        set idx to item i of targetIndices
                        set expectedId to item i of targetIds
                        set isStrict to item i of targetStricts
                        
                        try
                            set theMessage to message idx of mb
                            set msgId to id of theMessage
                            
                            if msgId is not expectedId then
                                -- Fallback se l'indice è slittato (es. nuovi messaggi arrivati in mailbox)
                                set theMessage to (first message of mb whose id is expectedId)
                                set msgId to id of theMessage
                            end if
                            
                            -- Gestione allegati
                            set attachmentNames to {{}}
                            set theAttachments to mail attachments of theMessage
                            set hasAtts to (count of theAttachments) > 0
                            
                            if isStrict or hasAtts then
                                set msgContent to source of theMessage
                            else
                                set msgContent to "[Corpo non scaricato - email di servizio/non rilevante]"
                            end if
                            
                            repeat with theAttachment in theAttachments
                                try
                                    set attName to name of theAttachment
                                    set end of attachmentNames to attName
                                    set saveAtt to false
                                    if attName ends with ".csv" or attName ends with ".xlsx" or attName ends with ".xls" or attName ends with ".CSV" or attName ends with ".XLSX" or attName ends with ".XLS" then
                                        set attNameStr to (attName as string)
                                        if attNameStr contains "iscritti" or attNameStr contains "report" or attNameStr contains "ade" or attNameStr contains "adm" or attNameStr contains "usb" or attNameStr contains "mef" or attNameStr contains "partecipanti" or attNameStr contains "anagrafica" or attNameStr contains "corso" or attNameStr contains "soci" or attNameStr contains "paypal" or attNameStr contains "banca" or attNameStr contains "estratto" then
                                            set saveAtt to true
                                        end if
                                    end if
                                    if saveAtt then
                                        set savePath to (destFolder & "/" & msgId & "_" & attName)
                                        save theAttachment in POSIX file savePath
                                    end if
                                end try
                            end repeat
                            
                            set oldDelims to AppleScript's text item delimiters
                            set AppleScript's text item delimiters to ", "
                            set attListStr to attachmentNames as string
                            set AppleScript's text item delimiters to oldDelims
                            
                            -- Output strutturato
                            set outText to outText & "[[MSG_START]]\\n"
                            set outText to outText & "ID: " & msgId & "\\n"
                            set outText to outText & "Attachments: " & attListStr & "\\n"
                            set outText to outText & "[[BODY_START]]\\n" & msgContent & "\\n[[MSG_END]]\\n"
                        on error err
                            set outText to outText & "[[MSG_START]]\\n"
                            set outText to outText & "ID: " & expectedId & "\\n"
                            set outText to outText & "ERROR: " & err & "\\n"
                            set outText to outText & "[[MSG_END]]\\n"
                        end try
                    end repeat
                    return outText
                end timeout
            end tell
            """
            
            try:
                print(f"  - Fase 3 (Lotti): Invio AppleScript per messaggi {start_chunk} a {start_chunk + len(chunk)}...", flush=True)
                t0_batch = time.time()
                details_output = run_applescript(fetch_details_script)
                print(f"  - Fase 3 (Lotti): AppleScript completato in {time.time() - t0_batch:.2f}s. Scrittura file in corso...", flush=True)
                chunk_written = parse_and_write_messages(details_output, raw_mail_dir, attachments_dir, metadata_lookup)
                mailbox_synced += chunk_written
                total_new_synced += chunk_written
                
                print(f"  - Fase 3 (Lotti): Scaricati {min(start_chunk + batch_size, total_missing)}/{total_missing} messaggi rilevanti...", flush=True)
            except Exception as e:
                print(f"  - Errore durante lo scaricamento del lotto {start_chunk}: {e}", flush=True)
                
        print(f"  - Completato: {mailbox_synced} nuove email sincronizzate per '{mb_path}'.")
        
    return total_new_synced


