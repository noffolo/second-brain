import os
import sys
import re
import argparse
import asyncio
import datetime
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

# Load env variables at startup
load_dotenv()

from engine.tools.notion_tools import notion_sync_to_raw
from engine.tools.notion_calendar import notion_calendar_sync
from engine.tools.notion_tasks import notion_tasks_sync
from engine.tools.drive_tools import drive_sync_to_raw
from engine.tools.mail_tools import apple_mail_sync_to_raw
from engine.tools.web_tools import web_sync_to_raw
from engine.tools.calendar_tools import calendar_sync_to_raw
from engine.ingest_agent import run_ingest
from engine.query_agent import run_interactive_loop, run_chat_watcher, run_single_query
from engine.reflect_agent import run_reflection
from engine.lint_agent import run_lint
from engine.tools.vault_tools import get_vault_path, write_wiki_page, append_to_log
from engine.git_ops import auto_commit, export_clean_codebase
from engine.ontology_agent import (
    generate_ontology_proposals,
    apply_negotiated_ontology,
    approve_proposal
)

def handle_notion_full_sync() -> int:
    count = notion_sync_to_raw()
    count += notion_calendar_sync()
    count += notion_tasks_sync()
    return count

def handle_sync(source: str = None):
    print("Avvio sincronizzazione delle fonti...")
    notion_count, drive_count, mail_count, web_count, cal_count = 0, 0, 0, 0, 0
    
    if source == "notion":
        notion_count = handle_notion_full_sync()
    elif source == "drive":
        drive_count = drive_sync_to_raw()
    elif source == "mail":
        mail_count = apple_mail_sync_to_raw()
    elif source == "web":
        web_count = asyncio.run(web_sync_to_raw())
    elif source == "calendar":
        cal_count = calendar_sync_to_raw()
    elif source is None:
        print("Avvio sincronizzazione delle fonti in PARALLELO...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_notion = executor.submit(handle_notion_full_sync)
            future_drive = executor.submit(drive_sync_to_raw)
            future_mail = executor.submit(apple_mail_sync_to_raw)
            future_cal = executor.submit(calendar_sync_to_raw)
            
            notion_count = future_notion.result()
            drive_count = future_drive.result()
            mail_count = future_mail.result()
            cal_count = future_cal.result()
            
        print("Avvio sincronizzazione Web...")
        web_count = asyncio.run(web_sync_to_raw())
    else:
        print(f"Sorgente di sincronizzazione sconosciuta: {source}")
        return 0, 0, 0, 0, 0
        
    print(f"Sincronizzazione completata: Notion ({notion_count} pagine/elementi), Drive ({drive_count} file), Mail ({mail_count} email), Web ({web_count} pagine), Calendario ({cal_count} eventi).")
    return notion_count, drive_count, mail_count, web_count, cal_count


def handle_journal(text: str):
    vault_path = get_vault_path()
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    journal_path = f"journal/{today_str}.md"
    abs_path = os.path.join(vault_path, journal_path)
    
    timestamp = datetime.datetime.now().strftime("%H:%M")
    new_entry = f"\n### Diario {timestamp}\n{text}\n"
    
    # Read old if exists
    body = ""
    fm = {
        "type": "journal",
        "date": today_str
    }
    
    if os.path.exists(abs_path):
        try:
            from engine.utils.markdown import parse_markdown
            with open(abs_path, "r", encoding="utf-8") as f:
                _, old_body = parse_markdown(f.read())
                body = old_body + "\n"
        except Exception:
            pass
            
    body += new_entry
    write_wiki_page(journal_path, body, fm)
    
    append_to_log(f"[Diario] Registrata nuova nota giornaliera in [[{today_str}]]")
    auto_commit(vault_path, f"[User Journal] Aggiunta nota giornaliera {today_str}")
    print(f"Nota di diario registrata in {journal_path}")

def handle_crm(name: str, notes: str):
    vault_path = get_vault_path()
    clean_name = re.sub(r'[\\/*?:"<>|]', "", name)
    crm_path = f"CRM/{clean_name}.md"
    
    fm = {
        "type": "crm_contact",
        "name": name
    }
    
    body = f"# {name}\n\n## Note\n{notes}\n"
    
    write_wiki_page(crm_path, body, fm)
    
    # Update CRM Index
    index_path = os.path.join(vault_path, "CRM", "index.md")
    index_entry = f"- [[CRM/{clean_name}|{name}]]\n"
    
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        if f"[[CRM/{clean_name}" not in content:
            with open(index_path, "a", encoding="utf-8") as f:
                f.write(index_entry)
    else:
        # Create crm index
        index_body = f"# CRM Contatti\n\nElenco dei contatti censiti nel Secondo Cervello:\n\n{index_entry}"
        write_wiki_page("CRM/index.md", index_body, {"type": "crm_index"})
        
    append_to_log(f"[CRM] Aggiunto/aggiornato contatto [[{clean_name}]]")
    auto_commit(vault_path, f"[User CRM] Aggiunto/aggiornato contatto {name}")
    print(f"Contatto {name} salvato in {crm_path}")

def main():
    parser = argparse.ArgumentParser(description="CLI Orchestrator per Secondo Cervello LLM Wiki")
    subparsers = parser.add_subparsers(dest="command", help="Comando da eseguire")
    
    # Ingest
    parser_ingest = subparsers.add_parser("ingest", help="Sync fonti + processa raw files + auto commit")
    parser_ingest.add_argument("--dry-run", action="store_true", help="Mostra solo i file da elaborare senza procedere")
    parser_ingest.add_argument("--source", type=str, default=None, help="Filtra i file da elaborare per sorgente (es. mail, notion, drive)")
    
    # Query
    parser_query = subparsers.add_parser("query", help="Chat interattiva CLI col secondo cervello")
    parser_query.add_argument("question", type=str, nargs="?", default=None, help="Domanda singola da porre al secondo cervello")
    
    # Watch chat
    subparsers.add_parser("watch-chat", help="Daemon watcher che risponde nel file chat.md")
    
    # Briefing
    subparsers.add_parser("briefing", help="Invia briefing pre-evento via mail")
    
    # Dream
    subparsers.add_parser("dream", help="Esegue la modalità sogno notturna per connettere nodi")
    
    # Reflect
    subparsers.add_parser("reflect", help="Genera riflessione periodica settimanale")
    
    # Lint
    subparsers.add_parser("lint", help="Esegue audit del wiki (link interrotti, orfani)")
    
    # Sync
    subparsers.add_parser("sync", help="Sincronizza Notion e Google Drive senza elaborare")
    
    # Journal
    parser_journal = subparsers.add_parser("journal", help="Aggiunge una entry al diario di oggi")
    parser_journal.add_argument("text", type=str, help="Contenuto della nota di diario")
    
    # CRM
    parser_crm = subparsers.add_parser("crm", help="Aggiunge o aggiorna un contatto nel CRM")
    parser_crm.add_argument("name", type=str, help="Nome della persona")
    parser_crm.add_argument("notes", type=str, help="Dettagli/note sulla persona")
    
    # Export clean codebase
    parser_export = subparsers.add_parser("export-clean", help="Esporta la codebase pulita (senza vault e dati) in un'altra cartella")
    parser_export.add_argument("target_dir", type=str, help="Directory di destinazione per la codebase pulita")
    
    # Ontology
    parser_ontology = subparsers.add_parser("ontology", help="Gestione ontologia emergente (genera o applica modifiche)")
    parser_ontology.add_argument("--apply", action="store_true", help="Applica le proposte ontologiche spuntate")
    parser_ontology.add_argument("--approve", type=str, default=None, help="Spunta programmaticamente una proposta con ID specifico")
    
    # Distill
    parser_distill = subparsers.add_parser("distill", help="Distilla un documento complesso generando un dossier .docx")
    parser_distill.add_argument("file_path", type=str, help="Percorso del file da distillare")
    parser_distill.add_argument("lang", type=str, nargs="?", default="it", help="Lingua di destinazione (it/en)")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(0)
        
    if args.command == "sync":
        handle_sync()
        
    elif args.command == "ingest":
        if not args.dry_run:
            # First sync, then ingest
            handle_sync(source=args.source)
        asyncio.run(run_ingest(dry_run=args.dry_run, source_filter=args.source))
        
    elif args.command == "query":
        if args.question:
            asyncio.run(run_single_query(args.question))
        else:
            asyncio.run(run_interactive_loop())
        
    elif args.command == "watch-chat":
        asyncio.run(run_chat_watcher())
        
    elif args.command == "briefing":
        from engine.briefing_daemon import run_briefing_daemon
        asyncio.run(run_briefing_daemon())
        
    elif args.command == "dream":
        from engine.dream_daemon import run_dream_mode
        asyncio.run(run_dream_mode())
        
    elif args.command == "reflect":
        asyncio.run(run_reflection())
        
    elif args.command == "lint":
        run_lint()
        
    elif args.command == "journal":
        handle_journal(args.text)
        
    elif args.command == "crm":
        handle_crm(args.name, args.notes)
        
    elif args.command == "export-clean":
        export_clean_codebase(get_vault_path(), args.target_dir)
        
    elif args.command == "ontology":
        if args.apply:
            apply_negotiated_ontology()
        elif args.approve:
            approve_proposal(args.approve)
        else:
            asyncio.run(generate_ontology_proposals())

    elif args.command == "distill":
        import subprocess
        python_exe = sys.executable
        script_path = os.path.join(os.path.dirname(__file__), "skills", "doc-distiller", "scripts", "doc_distiller.py")
        subprocess.run([python_exe, script_path, args.file_path, args.lang])

if __name__ == "__main__":
    main()
