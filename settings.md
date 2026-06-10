---
# Timing dei Servizi in Background (launchd)
# Se modificati, eseguire `make install-service` per applicare le modifiche
timing:
  sync_and_ingest: "0 10 * * *"        # Esegui ogni giorno alle 10:00 (cron: "0 10 * * *")
  weekly_reflection: "0 21 * * 0"     # Domenica alle 21:00
  briefing: "300"                     # Esegui ogni 5 minuti (300 secondi)
  dream: "0 3 * * *"                  # Ogni notte alle 03:00 AM (cron: "0 3 * * *")

# Abilitazioni e Percorsi Sorgenti Esterne
sources:
  notion:
    enabled: true
    sync_all: true
    database_ids: ["6f4bd393f5394cd9ae70eeb83df9ed79", "8cf4fdfcd0e0471e82b37b323e597965", "d73ddfa6f4524279be2b2956a17aab45", "eaabfc93f45548779832470db0ea60e9", "9a5507065830472a9084673433fe825b", "53eb57f933814e0ab375748b120ce121"]
    calendar_database_id: "eaabfc93f45548779832470db0ea60e9"          # ID del database eventi/appuntamenti Notion
    tasks_database_id: "d73ddfa6f4524279be2b2956a17aab45"             # ID del database task Notion
  google_drive:
    enabled: false
    use_api: false
    folder_id: ""                     # ID della cartella Google Drive (es. dal link di condivisione)
    resource_key: ""                  # Chiave risorsa (opzionale, es. dal link se richiesto)
    local_path: "~/Google Drive/Il mio Drive"
  apple_mail:
    enabled: true                    # Imposta a true per abilitare Apple Mail
    sync_all_accounts: true           # Imposta a true per sincronizzare tutti gli account configurati
    account_prefix: ""                # Prefisso degli account mail da sincronizzare (es. "SB-", lasciare vuoto per tutti)
    mailbox: "SecondBrain"            # Utilizzato solo se sync_all_accounts è false
    days_back: 90                      # Importa lo storico delle email (0 = tutte le email)
    attachments_dir: "raw/mail_attachments"
    exclude_senders: ["noreply@", "newsletter@", "no-reply@", "promo@", "marketing@", "substack-updates@"]
    exclude_domains: ["glovoapp.com", "glovo.com", "gog.com", "booking.com", "promo.booking.com", "airbnb.com", "spotify.com", "diib.com", "coinbase.com", "crunchyroll.com", "medium.com", "ibs.it", "ifttt.com", "klingai.com", "repubblica.it"]
    exclude_subjects: ["codice sconto", "accesso temporaneo", "accesso da nuovo", "daily digest", "mancato recapito", "fattura elettronica", "avviso di accesso", "promozionale"]

  mail_accounts:                     # Configura qui una lista di account IMAP per la sincronizzazione di caselle email multiple
    # - enabled: true
    #   server: "imaps.aruba.it"
    #   port: 993
    #   username: "alessandro@ff3300.com"
    #   mailbox: "INBOX"
    #   password_env: "IMAP_PASSWORD_1"
    # - enabled: true
    #   server: "imap.gmail.com"
    #   port: 993
    #   username: "altra_mail@gmail.com"
    #   mailbox: "INBOX"
    #   password_env: "IMAP_PASSWORD_2"


  web:
    enabled: false
    urls:
      - "https://www.thetoolnerd.com/p/step-by-step-guide-build-your-own-second-brain-obsidian-kaparthy"
      - "https://medium.com/@roanmonteiro/building-a-complete-personal-harness-llm-wiki-developers-second-brain-in-obsidian-d7b61c7398ff"
      - "https://www.askglitch.com/blog/build-a-second-brain"
      - "https://aimaker.substack.com/p/llm-wiki-obsidian-knowledge-base-andrej-karphaty"

  google_calendar:
    enabled: true
    urls:
      - "https://calendar.google.com/calendar/ical/example%40gmail.com/public/basic.ics"

  meeting_agent:
    enabled: true
    meetings_dir: "Meetings"
    people_dir: "People"
    microthemes_dir: "Microthemes"

# Configurazione dei Modelli Generativi (Gemini)
models:
  query_agent: "gemini-3.5-flash"     # Utilizza gemini-3.5-flash come default consigliato
  ingest_agent: "gemini-3.5-flash"
  reflect_agent: "gemini-3.5-flash"
  temperature: 0.2


# Autenticazione Google Cloud / Vertex AI (Alternativa a API Key)
google_auth:
  use_vertex: false                   # Imposta a true per usare Vertex AI / Application Default Credentials
  project_id: ""                      # ID del progetto Google Cloud (opzionale)
  location: "us-central1"             # Regione Vertex AI (default: us-central1)

# Altre preferenze di sistema
preferences:
  auto_commit: true
  git_author: "Second Brain Agent <agent@secondbrain.local>"
---

# Configurazione del Secondo Cervello

Questo file contiene i parametri di configurazione del Secondo Cervello. Puoi modificare liberamente i valori nel blocco YAML frontmatter sovrastante.

## Note sui Parametri

- **timing**: I valori supportati sono in formato cron standard a 5 campi (minuto ora giorno-del-mese mese giorno-della-settimana) oppure un numero intero che rappresenta l'intervallo in secondi. Se aggiornato, dovrai rieseguire `make install-service`.
- **sources.meeting_agent**: Quando abilitato, l'agente di ingestion scansionerà le note verbali in `Meetings/` e i microtemi in `Microthemes/` prodotti dal tool `meeting-agent` per integrarli nel Secondo Cervello.
- **sources.notion**: Richiede la presenza di `NOTION_TOKEN` nel file `.env`.
- **sources.google_drive**: Percorso locale per la sincronizzazione da Google Drive.
