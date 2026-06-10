import os
import re
import json
import datetime
import asyncio
from dotenv import load_dotenv

from engine.utils.markdown import load_settings, parse_markdown, to_markdown
from engine.utils.llm_fallback import call_llm_with_fallback
from engine.utils.email_sender import send_email
from engine.tools.vault_tools import get_vault_path, search_wiki, update_frontmatter
from google.antigravity import LocalAgentConfig

def parse_datetime(dt_str: str) -> datetime.datetime or None:
    if not dt_str:
        return None
    # Strip timezone suffix for comparison if present
    dt_str = dt_str.replace(" UTC", "").strip()
    
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d"
    ]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(dt_str, fmt)
        except Exception:
            pass
    return None

def find_upcoming_unbriefed_events(vault_path: str) -> list[tuple[str, dict, str]]:
    """
    Scansiona wiki/entities/ e raw/calendar/ per trovare eventi con start_time tra 5 e 20 minuti nel futuro
    e che non contengano briefed: true nel frontmatter.
    Ritorna una lista di tuple (rel_path, frontmatter, body_content).
    """
    upcoming = []
    scan_dirs = [
        os.path.join(vault_path, "wiki", "entities"),
        os.path.join(vault_path, "raw", "calendar")
    ]
    
    now = datetime.datetime.now()
    window_start = now + datetime.timedelta(minutes=5)
    window_end = now + datetime.timedelta(minutes=20)
    
    for scan_dir in scan_dirs:
        if not os.path.exists(scan_dir):
            continue
        for root, _, files in os.walk(scan_dir):
            for file in files:
                if file.endswith(".md") and not file.startswith("."):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            content = f.read()
                        fm, body = parse_markdown(content)
                        
                        if fm.get("type") in ["calendar_event", "appointment"] and not fm.get("briefed", False):
                            start_time_str = fm.get("start_time", "")
                            dt_start = parse_datetime(start_time_str)
                            
                            if dt_start:
                                # Se l'evento ha data+ora (non solo data) e cade nel window
                                if len(start_time_str) > 10:  # e.g., longer than YYYY-MM-DD
                                    if window_start <= dt_start <= window_end:
                                        rel_path = os.path.relpath(filepath, vault_path)
                                        upcoming.append((rel_path, fm, body))
                    except Exception:
                        pass
    return upcoming

async def generate_briefing_text(event_fm: dict, event_body: str, context_notes: list[dict], config: LocalAgentConfig) -> str:
    title = event_fm.get("title", "Appuntamento imminente")
    start_time = event_fm.get("start_time", "")
    location = event_fm.get("location", "Non specificato")
    organizer = event_fm.get("organizer", "Non specificato")
    attendees = event_fm.get("attendees", [])
    
    # Format context snippets
    context_str = ""
    if context_notes:
        for note in context_notes[:10]:
            context_str += f"### Nota: {note['title']} (Percorso: {note['path']})\n"
            context_str += f"Snippet: {note['snippet']}\n\n"
    else:
        context_str = "Nessuna nota o contatto direttamente correlato trovato nel Secondo Cervello."
        
    system_instructions = """
    Sei l'assistente del Secondo Cervello dell'utente. Il tuo compito è generare un briefing email sintetico e utilissimo prima di un appuntamento.
    Il briefing deve contestualizzare l'incontro raccogliendo note passate, persone del CRM e focus emersi dai diari.
    Fornisci indicazioni strategiche sui temi da affrontare, punti critici storici, e su chi sono le persone coinvolte.
    Parla in prima persona come assistente dell'utente. Usa un tono acuto, limpido, sintetico ma profondo (in italiano).
    Garantisci che il testo sia formattato in Markdown pulito, senza racchiuderlo in blocchi di codice markdown (come ``` o ```markdown).
    Evita la capitalizzazione in stile inglese (es. usa le maiuscole solo dove richiesto dalla grammatica italiana).
    
    REGOLA DI FERRO CONTRO LE ALLUCINAZIONI (CRITICAL):
    Non devi MAI inventare o ipotizzare dettagli, fatti, date, persone o relazioni. Devi attenerti RIGOROSAMENTE ed ESCLUSIVAMENTE a ciò che sai o che sei CERTO di aver capito dal contesto fornito. È infinitamente meglio scrivere "non ci sono ulteriori informazioni" piuttosto che fare supposizioni o inventare anche un solo dettaglio. Se non hai prove certe e documentate nei file forniti, dichiara esplicitamente la mancanza di informazioni.
    """
    
    prompt = f"""
    Genera un briefing email per questo appuntamento che si terrà tra 15 minuti:
    - Titolo: {title}
    - Ora: {start_time}
    - Luogo: {location}
    - Organizzatore: {organizer}
    - Partecipanti: {', '.join(attendees) if attendees else 'Nessuno specificato'}
    
    Contenuto dell'evento:
    {event_body}
    
    Informazioni contestuali estratte dal Secondo Cervello:
    {context_str}
    
    Struttura il briefing in 3-4 brevi sezioni:
    ## 1. CONTESTO GENERALE & CHI COINVOLGE: chi sono le persone rilevanti e la loro storia (dal CRM/note).
    ## 2. TEMI CHIAVE & CRONOLOGIA: ultime discussioni emerse dai verbali dei meeting o dal diario.
    ## 3. PUNTI APERTI & COSA CHIEDERE: suggerimenti strategici su cosa affrontare o chiarire.
    
    REGOLA DI FERRO: Se non ci sono informazioni contestuali o dettagli certi su uno dei punti sopra, non inventare NULLA. Scrivi semplicemente "non ci sono ulteriori informazioni" per quella sezione o per quel punto specifico.
    
    IMPORTANTE: Scrivi direttamente il testo dell'email in formato Markdown standard (es. intestazioni con ##, grassetti con **, liste con -).
    NON includere delimitatori di blocco codice come ``` o ```markdown all'inizio o alla fine del testo.
    """
    
    try:
        return await call_llm_with_fallback(prompt, system_instructions, config)
    except Exception as e:
        print(f"Errore nella generazione LLM del briefing: {e}")
        return f"Briefing per l'evento '{title}'.\nErrore durante la generazione automatica: {e}"

async def run_briefing_daemon():
    load_dotenv()
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    
    # 1. Trova eventi imminenti non ancora notificati
    upcoming = find_upcoming_unbriefed_events(vault_path)
    if not upcoming:
        print("Nessun evento imminente (tra 5 e 20 minuti) da notificare.")
        return
        
    # 2. Configura il modello
    model = settings.get("models", {}).get("query_agent", "gemini-3.5-flash")
    auth = settings.get("google_auth", {})
    kwargs = {}
    if auth.get("use_vertex", False):
        kwargs["vertex"] = True
        if auth.get("project_id"):
            kwargs["project"] = auth["project_id"]
        if auth.get("location"):
            kwargs["location"] = auth["location"]
            
    config = LocalAgentConfig(
        model=model,
        system_instructions="Sei un assistente email per il secondo cervello.",
        **kwargs
    )
    
    for rel_path, fm, body in upcoming:
        title = fm.get("title", "Appuntamento")
        print(f"Elaborazione briefing per l'evento imminente: '{title}'...")
        
        # 3. Raccogli note correlate tramite ricerca testuale
        # Estrai parole chiave dal titolo
        keywords = re.findall(r'\w{4,}', title)
        context_notes = []
        for kw in keywords[:3]:
            context_notes.extend(search_wiki(kw))
            
        # Rimuovi duplicati basandoti sul percorso
        seen_paths = set()
        unique_context = []
        for note in context_notes:
            # Salta la nota dell'evento stessa
            if note["path"] == rel_path:
                continue
            if note["path"] not in seen_paths:
                seen_paths.add(note["path"])
                unique_context.append(note)
                
        # 4. Genera il briefing
        briefing_text = await generate_briefing_text(fm, body, unique_context, config)
        
        # 5. Invia l'email
        subject = f"[Secondo Cervello] Briefing pre-evento: {title}"
        success = send_email(subject, briefing_text)
        
        # 6. Segna come briefed per evitare doppi invii
        if success or True:  # Segniamo comunque a true per evitare loop in caso di SMTP non configurato
            try:
                update_frontmatter(rel_path, {"briefed": True})
                print(f"Evento '{title}' contrassegnato come briefed.")
            except Exception as e:
                print(f"Errore durante l'aggiornamento frontmatter per {rel_path}: {e}")

if __name__ == "__main__":
    asyncio.run(run_briefing_daemon())
