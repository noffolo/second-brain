import os
import re
import urllib.request
import urllib.parse
import ssl
import asyncio
import datetime
from engine.utils.markdown import load_settings, parse_markdown, to_markdown
from engine.utils.llm_fallback import call_llm_with_fallback
from google.antigravity import LocalAgentConfig

try:
    ssl_context = ssl._create_unverified_context()
except AttributeError:
    ssl_context = None

def get_vault_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def url_to_filename(url: str) -> str:
    # Rimuovi protocollo
    clean = re.sub(r'^https?://', '', url)
    # Sostituisci caratteri speciali con underscore
    clean = re.sub(r'[^a-zA-Z0-9]', '_', clean)
    # Rimuovi underscore duplicati
    clean = re.sub(r'_+', '_', clean).strip('_')
    # Riduci lunghezza se eccessiva
    if len(clean) > 150:
        clean = clean[:150]
    return clean + ".md"

def clean_raw_html(html: str) -> str:
    # Rimuovi tag inutili e pesanti
    html = re.sub(r'<script.*?>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style.*?>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<svg.*?>.*?</svg>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<nav.*?>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<footer.*?>.*Original footer.*</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    
    # Estrai solo il body se presente per ridurre drasticamente la dimensione
    body_match = re.search(r'<body.*?>(.*?)</body>', html, flags=re.DOTALL | re.IGNORECASE)
    if body_match:
        html = body_match.group(1)
        
    # Compatta gli spazi bianchi per risparmiare token
    html = re.sub(r'\s+', ' ', html)
    return html.strip()[:100000]

async def fetch_and_clean_webpage(url: str, config: LocalAgentConfig) -> str:
    print(f"Scaricamento della pagina: {url}...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    req = urllib.request.Request(url, headers=headers)
    
    # Esegui la richiesta HTTP sincrona in un thread pool
    loop = asyncio.get_running_loop()
    try:
        def do_request():
            with urllib.request.urlopen(req, context=ssl_context, timeout=30) as response:
                return response.read().decode("utf-8", errors="ignore")
        raw_html = await loop.run_in_executor(None, do_request)
    except Exception as e:
        print(f"Errore nel download di {url}: {e}")
        return f"# Errore di connessione\n\nImpossibile scaricare la pagina {url}.\nErrore: {e}"

    cleaned_html = clean_raw_html(raw_html)
    
    system_instructions = """
Sei un estrattore ed elaboratore di contenuti web per un Secondo Cervello.
Il tuo compito è convertire l'HTML grezzo o il testo fornito in un documento Markdown pulito (.md).
Rimuovi intestazioni di navigazione, pubblicità, banner di cookie, sidebar, footer e altri elementi non pertinenti.
Conserva il testo principale dell'articolo, la formattazione (titoli, liste, corsivo, grassetto) e i link importanti.
Aggiungi all'inizio del file un blocco frontmatter YAML che rispetti esattamente questa struttura:
---
title: "Titolo dell'articolo"
author: "Nome dell'autore (se rilevabile, altrimenti null)"
date: "Data di pubblicazione YYYY-MM-DD (se rilevabile, altrimenti data odierna)"
source_url: "URL sorgente fornito"
type: "web_article"
tags: ["tag1", "tag2", ...] (almeno 3 tag pertinenti sul contenuto)
---
Restituisci solo ed esclusivamente il contenuto markdown dell'articolo con il frontmatter. Non inserire altri commenti prima o dopo il blocco.
"""
    
    prompt = f"""
Converti questa pagina web in markdown con il frontmatter corretto.
Sorgente URL: {url}

HTML/Testo della pagina:
{cleaned_html}
"""
    
    print(f"Elaborazione con LLM del contenuto di: {url}...")
    try:
        cleaned_markdown = await call_llm_with_fallback(prompt, system_instructions, config)
        return cleaned_markdown
    except Exception as e:
        print(f"Errore durante l'elaborazione LLM per {url}: {e}")
        return f"""---
title: "Errore elaborazione"
source_url: "{url}"
type: "web_article"
tags: ["errore"]
---
# Errore Elaborazione LLM
Non è stato possibile elaborare la pagina tramite LLM.
Errore: {e}
"""

async def web_sync_to_raw() -> int:
    """
    Sincronizza i siti web configurati in settings.md scaricandone i contenuti,
    convertendoli in markdown pulito tramite LLM e salvandoli in raw/web_articles/.
    """
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    
    web_settings = settings.get("sources", {}).get("web", {})
    if not web_settings.get("enabled", False):
        print("Sorgente Web disabilitata nelle impostazioni.")
        return 0
        
    urls = web_settings.get("urls", [])
    if not urls:
        print("Nessun URL configurato per la sorgente Web in settings.md.")
        return 0
        
    dest_dir = os.path.join(vault_path, "raw", "web_articles")
    os.makedirs(dest_dir, exist_ok=True)
    
    # Configura l'agente per l'elaborazione del testo
    model = settings.get("models", {}).get("ingest_agent", "gemini-3.5-flash")
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
        system_instructions="Sei un assistente per la conversione di pagine HTML in Markdown.",
        **kwargs
    )
    
    synced_count = 0
    for url in urls:
        if not url.strip():
            continue
            
        filename = url_to_filename(url)
        filepath = os.path.join(dest_dir, filename)
        
        # Salta se già sincronizzato per evitare chiamate LLM duplicate e sovraccarichi
        if os.path.exists(filepath):
            # Controlla se il file non è vuoto o un errore di connessione/elaborazione precedente
            with open(filepath, "r", encoding="utf-8") as f:
                head = f.read(500)
            if "Errore di connessione" not in head and "Errore Elaborazione LLM" not in head:
                # Pagina già scaricata con successo
                continue
        
        # Scarica ed elabora
        markdown_content = await fetch_and_clean_webpage(url, config)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(markdown_content)
            
        synced_count += 1
        print(f"Sincronizzato e salvato: {url} -> raw/web_articles/{filename}")
        # Piccolo delay per evitare rate limit
        await asyncio.sleep(1)
        
    return synced_count

if __name__ == "__main__":
    asyncio.run(web_sync_to_raw())
