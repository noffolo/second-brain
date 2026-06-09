import os
import re
import urllib.request
import ssl
import datetime
from engine.utils.markdown import load_settings

try:
    ssl_context = ssl._create_unverified_context()
except AttributeError:
    ssl_context = None

def get_vault_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def unescape_ical_text(text: str) -> str:
    if not text:
        return ""
    # Unescape commas, semicolons, backslashes, and newlines
    text = text.replace(r'\,', ',').replace(r'\;', ';').replace(r'\\', '\\')
    text = re.sub(r'\\n|\\N', '\n', text)
    return text.strip()

def parse_ical_datetime(val: str) -> str:
    # DTSTART value can be:
    # 20260609T133000Z (UTC)
    # 20260609T133000 (Local floating)
    # TZID=Europe/Rome:20260609T133000 (we strip the TZID part first)
    if ":" in val:
        val = val.split(":")[-1]
    
    val = val.strip()
    is_utc = val.endswith("Z")
    clean_val = val.replace("Z", "")
    
    try:
        if "T" in clean_val:
            dt = datetime.datetime.strptime(clean_val, "%Y%m%dT%H%M%S")
        else:
            dt = datetime.datetime.strptime(clean_val, "%Y%m%d")
            # If it's a date-only, return just the date
            return dt.strftime("%Y-%m-%d")
            
        if is_utc:
            return dt.strftime("%Y-%m-%d %H:%M:%S") + " UTC"
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return val

def parse_ics_content(ics_text: str) -> list[dict]:
    # 1. Unfold lines (remove CR and handle continuation lines starting with space/tab)
    lines = []
    for line in ics_text.splitlines():
        if not line:
            continue
        if line[0] in (' ', '\t'):
            if lines:
                lines[-1] += line[1:]
        else:
            lines.append(line)
            
    events = []
    current_event = None
    
    for line in lines:
        if line.startswith("BEGIN:VEVENT"):
            current_event = {
                "uid": "",
                "summary": "Evento senza titolo",
                "description": "",
                "location": "",
                "dtstart": "",
                "dtend": "",
                "organizer": "",
                "attendees": []
            }
        elif line.startswith("END:VEVENT"):
            if current_event:
                events.append(current_event)
                current_event = None
        elif current_event is not None:
            # Parse property key and value
            match = re.match(r'^([A-Z0-9\-;=,]+):(.*)$', line, re.IGNORECASE)
            if match:
                key_part, val = match.groups()
                key = key_part.split(";")[0].upper()
                
                if key == "UID":
                    current_event["uid"] = val.strip()
                elif key == "SUMMARY":
                    current_event["summary"] = unescape_ical_text(val)
                elif key == "DESCRIPTION":
                    current_event["description"] = unescape_ical_text(val)
                elif key == "LOCATION":
                    current_event["location"] = unescape_ical_text(val)
                elif key == "DTSTART":
                    current_event["dtstart"] = parse_ical_datetime(val)
                elif key == "DTEND":
                    current_event["dtend"] = parse_ical_datetime(val)
                elif key == "ORGANIZER":
                    cn_match = re.search(r'CN=([^;:]+)', key_part, re.IGNORECASE)
                    if cn_match:
                        current_event["organizer"] = cn_match.group(1).strip('"')
                    else:
                        current_event["organizer"] = val.replace("mailto:", "").strip()
                elif key == "ATTENDEE":
                    cn_match = re.search(r'CN=([^;:]+)', key_part, re.IGNORECASE)
                    if cn_match:
                        current_event["attendees"].append(cn_match.group(1).strip('"'))
                    else:
                        email = val.replace("mailto:", "").strip()
                        if email:
                            current_event["attendees"].append(email)
                            
    return events

def calendar_sync_to_raw() -> int:
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    
    cal_settings = settings.get("sources", {}).get("google_calendar", {})
    if not cal_settings.get("enabled", False):
        print("Sorgente Google Calendar disabilitata nelle impostazioni.")
        return 0
        
    urls = cal_settings.get("urls", [])
    if not urls:
        print("Nessun URL configurato per la sorgente Google Calendar in settings.md.")
        return 0
        
    dest_dir = os.path.join(vault_path, "raw", "calendar")
    os.makedirs(dest_dir, exist_ok=True)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    total_events_synced = 0
    
    for url in urls:
        if not url.strip():
            continue
            
        print(f"Scaricamento calendario iCal da: {url}...")
        req = urllib.request.Request(url, headers=headers)
        
        try:
            with urllib.request.urlopen(req, context=ssl_context, timeout=30) as response:
                raw_ics = response.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"Errore nel download del calendario da {url}: {e}")
            continue
            
        print("Parsing degli eventi iCal...")
        events = parse_ics_content(raw_ics)
        print(f"Trovati {len(events)} eventi nel calendario.")
        
        for ev in events:
            uid = ev["uid"]
            if not uid:
                uid = str(hash(ev["summary"] + ev["dtstart"]))
                
            clean_uid = re.sub(r'[^a-zA-Z0-9_\-]', '_', uid)
            filename = f"event_{clean_uid}.md"
            filepath = os.path.join(dest_dir, filename)
            
            fm = {
                "type": "calendar_event",
                "title": ev["summary"],
                "start_time": ev["dtstart"],
                "end_time": ev["dtend"],
                "location": ev["location"] or None,
                "organizer": ev["organizer"] or None,
                "attendees": ev["attendees"] or [],
                "source_url": url
            }
            
            body = f"# {ev['summary']}\n\n"
            body += f"**Inizio**: {ev['dtstart']}\n"
            if ev['dtend']:
                body += f"**Fine**: {ev['dtend']}\n"
            if ev['location']:
                body += f"**Luogo**: {ev['location']}\n"
            if ev['organizer']:
                body += f"**Organizzatore**: {ev['organizer']}\n"
            if ev['attendees']:
                body += f"**Partecipanti**:\n"
                for att in ev['attendees']:
                    body += f"- {att}\n"
                    
            if ev['description']:
                body += f"\n## Descrizione\n{ev['description']}\n"
                
            from engine.utils.markdown import to_markdown
            full_md = to_markdown(fm, body)
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(full_md)
                
            total_events_synced += 1
            
    print(f"Sincronizzazione calendario completata: salvati {total_events_synced} eventi in raw/calendar/.")
    return total_events_synced

if __name__ == "__main__":
    calendar_sync_to_raw()
