# 📘 MANUALE OPERATORE — SECONDO CERVELLO
## Guida Tecnica Completa per l'Amministrazione, Configurazione e Manutenzione

**Versione**: 1.0  
**Destinatari**: Operatori di sistema, Amministratori di rete e Sviluppatori  
**Ultimo aggiornamento**: Giugno 2026  
**Autore**: Secondo Cervello Development Team & Partner AI  

---

## Indice

1. [Introduzione e Filosofia del Progetto](#1-introduzione-e-filosofia-del-progetto)
2. [Architettura del Sistema e Struttura Directory](#2-architettura-del-sistema-e-struttura-directory)
3. [Procedura di Configurazione Wizard (`setup`)](#3-procedura-di-configurazione-wizard-setup)
4. [Sincronizzazione Fonti ed Ingestione](#4-sincronizzazione-fonti-ed-ingestione)
   - 4.1 [Notion Database e Synced Databases](#41-notion-database-e-synced-databases)
   - 4.2 [Google Calendar (iCal/ICS Segreti)](#42-google-calendar-icalics-segreti)
   - 4.3 [Aruba Mail (IMAP IDLE e Reattività)](#43-aruba-mail-imap-idle-e-reattivita)
5. [I Daemon in Background](#5-i-daemon-in-background)
   - 5.1 [File Watcher (`watcher.py`)](#51-file-watcher-watcherpy)
   - 5.2 [Briefing Daemon (`briefing_daemon.py`)](#52-briefing-daemon-briefing_daemonpy)
   - 5.3 [Dream Daemon (`dream_daemon.py`)](#53-dream-daemon-dream_daemonpy)
   - 5.4 [Reflect Agent (`reflect_agent.py`)](#54-reflect-agent-reflect_agentpy)
6. [Deploy, Portabilità e Background Services](#6-deploy-portabilita-e-background-services)
   - 6.1 [macOS (`launchd` Plist)](#61-macos-launchd-plist)
   - 6.2 [Linux (`systemd` User Services)](#62-linux-systemd-user-services)
7. [Strategia Git, Backup e Sicurezza dei Dati](#7-strategia-git-backup-e-sicurezza-des-dati)
8. [Risoluzione dei Problemi e Debugging](#8-risoluzione-dei-problemi-e-debugging)

---

## 1. Introduzione e Filosofia del Progetto

Il **Secondo Cervello** è una base di conoscenza (Vault) privata ed estensibile, strutturata su file Markdown locali ( Obsidian-compatible) e pilotata da un motore intelligente che integra Agent AI autonomi. 

La filosofia cardine è l'**assenza di lock-in**: tutti i dati risiedono in file di testo semplice sotto il controllo diretto dell'utente. Il motore software agisce come un'orchestra di processi deterministici (sincronizzazione, generazione di HTML, file watching) combinati a modelli generativi di linguaggio (LLM) usati esclusivamente per compiti semantici ad alto livello.

---

## 2. Architettura del Sistema e Struttura Directory

L'applicazione segue un'architettura **ibrida determinista-probabilistica**:
1. **Dati e Vault (Obsidian)**: Note scritte in Markdown in cartelle semantiche.
2. **Motore (Engine)**: Script Python in `engine/` che gestiscono la logica di sincronizzazione, i test, l'ontologia e i daemon.
3. **Pannello di Controllo (FastAPI)**: Web dashboard per la visualizzazione dello stato del sistema e l'attivazione dei sync.

### Struttura delle Directory

```
second_brain/
├── .env                  # Variabili d'ambiente segrete (SMTP, API Key, Token)
├── settings.md           # Configurazione YAML inclusa in una pagina Markdown (Single Source of Truth)
├── Makefile              # Automazione dei comandi (installazione, esecuzione, testing)
├── pyproject.toml        # Dipendenze e metadati del progetto Python
├── engine/               # Codice sorgente Python
│   ├── tools/            # Script helper per integrazioni (Notion, Mail, Calendar, Vault)
│   ├── utils/            # Script di utilità (invio email, fallback LLM, markdown parser)
│   ├── tests/            # Suite di test unitari (pytest)
│   ├── setup_wizard.py   # CLI interattiva per la prima configurazione
│   ├── systemd_generator.py # Generatore di file unit per Linux systemd
│   ├── plist_generator.py   # Generatore di file .plist per macOS launchd
│   └── main.py           # CLI entrypoint dell'applicazione
├── wiki/                 # Note strutturate (Conoscenza compilata)
│   ├── concepts/         # Note su concetti e argomenti astratti
│   ├── entities/         # Note su persone (CRM) ed eventi (Calendar)
│   └── synthesis/        # Sintesi notturne, riflessioni settimanali e report
├── CRM/                  # Profili personali dei contatti e relazioni
├── journal/              # Diari personali quotidiani
├── Meetings/             # Verbali e trascrizioni dei meeting
├── raw/                  # Dati grezzi scaricati dalle fonti esterne
│   ├── calendar/         # File ICS/Notion Calendar parzialmente elaborati
│   └── notion/           # JSON/MD grezzi scaricati da Notion
└── scratch/              # File temporanei persistenti o script di debug
```

---

## 3. Procedura di Configurazione Wizard (`setup`)

Per semplificare l'installazione su nuove macchine o server, il Secondo Cervello implementa un **Wizard CLI** interattivo.

### Esecuzione
Dalla cartella principale del progetto, esegui:
```bash
python -m engine.main setup
```

### Fasi del Wizard
1. **Configurazione Modello Generativo (LLM)**:
   - *Google AI Studio*: Richiede una chiave `GEMINI_API_KEY` (viene validata con una chiamata API di prova).
   - *Google Cloud Vertex AI*: Abilita l'autenticazione basata su credenziali cloud (Google Auth / ADC), ereditando le variabili di progetto e regione in tutti i fallback.
   - *Ollama (Locale)*: Chiede l'host (default `http://localhost:11434`) e il modello locale (es. `llama3`), testando la connessione al demone Ollama.
   - *DeepSeek*: Abilita la chiave `DEEPSEEK_API_KEY` ed imposta il provider.
2. **Integrazione Notion & Mappatura Database**:
   - Raccoglie il `NOTION_TOKEN` ed esegue una query di ricerca globale per trovare tutti i database condivisi con l'integrazione.
   - Mostra l'elenco numerato dei database e guida l'utente a selezionare quale database corrisponde al Calendario (Appuntamenti), quale ai Task e quali importare come generici (Clienti, Progetti, Documenti).
   - Scrive la mappatura direttamente in `settings.md`.
3. **Configurazione Mail Server (SMTP/IMAP Aruba)**:
   - Raccoglie i parametri Aruba (SMTP: `smtps.aruba.it` porta 465, IMAP: `imaps.aruba.it` porta 993).
   - Esegue un test di autenticazione in tempo reale sia in invio (SMTP) che in ricezione (IMAP) per assicurarsi che i parametri siano validi.
4. **Notifiche Telegram & GitHub**:
   - Configura opzionalmente il `TELEGRAM_BOT_TOKEN`, gli ID abilitati e le credenziali di GitHub per l'auto-push.

---

## 4. Sincronizzazione Fonti ed Ingestione

Il Secondo Cervello centralizza l'acquisizione della conoscenza da molteplici canali, normalizzandoli in formato Markdown all'interno del Vault.

### 4.1 Notion Database e Synced Databases

Il modulo di sincronizzazione di Notion interroga i database mappati per scaricare pagine nuove o modificate.

#### Risoluzione Synced Databases (Database Sincronizzati)
I database Notion che sono collegati a servizi esterni (come Google Calendar o Jira) non rispondono alle query standard API UUID, restituendo errori `Invalid request URL`. Il modulo in [notion_tools.py](engine/tools/notion_tools.py) supera questo limite:
1. Rileva se il database risponde con errore o se contiene riferimenti a `data_sources` esterne.
2. Interroga le impostazioni della sorgente dati interna di Notion.
3. Esegue la query estraendo le righe tramite la sorgente dati interna per garantire la continuità dei sync.

#### Mappatura dei Campi
- **Calendario**: Sincronizza Titolo, Data di Inizio (`start_time`), Luogo, Partecipanti e Corpo della pagina, salvando in `raw/calendar/`.
- **Task**: Sincronizza Titolo, Stato, Scadenza, ed effettua un sync **bidirezionale**: se un file markdown locale viene modificato, la modifica viene riportata su Notion alla successiva esecuzione.

---

### 4.2 Google Calendar (iCal/ICS Segreti)

Per sincronizzare i calendari personali senza esporli pubblicamente:
1. Nelle impostazioni di Google Calendar, copia l'**Indirizzo segreto in formato iCal** (un URL HTTPS che termina con `.ics`).
2. Aggiungilo alla lista `urls` all'interno di `settings.md` nella sezione `sources.google_calendar.urls`.
3. Lo script scaricherà il file ICS in modo sicuro via HTTPS e lo parserizzerà salvando gli eventi in `raw/calendar/`.

---

### 4.3 Aruba Mail (IMAP IDLE e Reattività)

Invece di eseguire il polling periodico (che consuma banda ed energia), il Secondo Cervello instaura una connessione persistente con la casella Aruba tramite protocollo **IMAP IDLE** in [mail_idle.py](engine/tools/mail_idle.py):
1. Invia il comando `IDLE` al server mail, rimanendo in attesa passiva di nuovi messaggi.
2. All'arrivo di una nuova email, la connessione si sblocca istantaneamente, scarica il messaggio e avvia la pipeline di sincronizzazione (`make ingest`).
3. Effettua un auto-refresh della sessione ogni 10 minuti per evitare disconnessioni forzate dai server Aruba.

---

## 5. I Daemon in Background

I daemon in background controllano il funzionamento automatico del Secondo Cervello e sono orchestrati tramite il ciclo di `lifespan` del server FastAPI.

```
       ┌────────────────── FASTAPI LIFESPAN ──────────────────┐
       │                                                      │
       │  ┌────────────────┐  ┌──────────────┐  ┌──────────┐  │
       │  │  File Watcher  │  │  IMAP IDLE   │  │ Briefing │  │
       │  │ (watchfiles)   │  │ (imapclient) │  │  Daemon  │  │
       │  └───────┬────────┘  └──────┬───────┘  └────┬─────┘  │
       │          │                  │               │        │
       │          ▼                  ▼               ▼        │
       │    [make ingest]      [make ingest]    [HTML Email]  │
       └──────────────────────────────────────────────────────┘
```

### 5.1 File Watcher (`watcher.py`)
Monitora le modifiche dei file markdown locali nelle cartelle sensibili (`raw/`, `Meetings/`, `journal/`).
- Utilizza la libreria `watchfiles` per rimanere in ascolto asincrono dei cambi di file.
- Applica un **debouncing** di 3 secondi: se riceve molteplici modifiche consecutive (come accade durante i sync di gruppo), attende che la scrittura si sia stabilizzata prima di avviare una singola ingestione per evitare sprechi di risorse.

### 5.2 Briefing Daemon (`briefing_daemon.py`)
Scansiona le cartelle `wiki/entities/` e `raw/calendar/` per trovare incontri non ancora notificati (`briefed: false`) e previsti a breve.
- **Finestra temporale**: Cerca eventi con ora di inizio compresa tra 5 e 20 minuti nel futuro.
- **Raccolta Contesto**: Rileva le parole chiave nel titolo dell'incontro e cerca note concetto correlate, verbali in `Meetings/` e profili di partecipanti nel CRM.
- **Generazione e Invio**: Un LLM sintetizza le informazioni in Markdown pulito. La funzione `send_email` di [email_sender.py](engine/utils/email_sender.py) converte il testo in tag HTML e invia un'email in formato `MIMEMultipart("alternative")` (HTML + Plain Text) con un foglio di stile elegante e responsive, contrassegnando l'evento con `briefed: true`.

### 5.3 Dream Daemon (`dream_daemon.py`)
Avviato ogni notte alle 03:00, effettua un'analisi semantica del Vault:
- Cerca concetti correlati ma non esplicitamente linkati, proponendoli come collegamenti `related` nel frontmatter delle note.
- Individua discrepanze o scadenze conflittuali.
- Compila una nota sintetica del "sogno" salvandola in `wiki/synthesis/dream_YYYY-MM-DD.md`.

### 5.4 Reflect Agent (`reflect_agent.py`)
Viene eseguito periodicamente per analizzare lo storico dell'attività settimanale, i diari e le note create, scrivendo una sintesi strutturata in `wiki/synthesis/YYYY-WNN_reflection.md` ed allineando i focus in `user_profile.md`.

---

## 6. Deploy, Portabilità e Background Services

La portabilità tra sistemi operativi differenti (es. sviluppo locale su macOS e deploy in produzione su server Linux) è gestita in modo nativo dal sistema di configurazione.

### 6.1 macOS (`launchd` Plist)
Su macOS, i servizi vengono installati come LaunchAgents per l'utente corrente.
- Il comando `make install-service` rileva l'OS e l'interprete Python e invoca `engine/plist_generator.py`.
- Genera i file `.plist` in `~/Library/LaunchAgents/` per la sincronizzazione, i briefing, il dream mode e la riflessione settimanale.
- Esegue `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/...` per attivarli.

### 6.2 Linux (`systemd` User Services)
Su distribuzioni Linux (Ubuntu, Debian, CentOS, ecc.), i servizi vengono gestiti tramite `systemd` in modalità utente (senza privilegi di root).
- `make install-service` rileva Linux ed invoca `engine/systemd_generator.py`.
- Crea le unit di servizio e di timer in `~/.config/systemd/user/`:
  - `secondbrain-dashboard.service` (avvia FastAPI con Uvicorn e attiva al suo interno il File Watcher ed il Mail Listener).
  - `secondbrain-briefing.service` + `secondbrain-briefing.timer` (esecuzione ogni 5 minuti).
  - `secondbrain-sync.service` + `secondbrain-sync.timer` (esecuzione giornaliera).
  - `secondbrain-dream.service` + `secondbrain-dream.timer` (esecuzione notturna).
- Esegue `systemctl --user daemon-reload` e `systemctl --user enable --now` per caricare i timer ed i servizi.

---

## 7. Strategia Git, Backup e Sicurezza dei Dati

Il Secondo Cervello implementa una strategia a **doppio repository** per bilanciare la condivisione open-source del codice e la riservatezza delle informazioni private:

1. **Repository Principale Privato (Snapshot)**:
   - È il repository locale principale. Collegato a una repo privata GitHub/GitLab, contiene sia il codice sorgente che tutti i dati personali (`wiki/`, `CRM/`, `journal/`).
   - Il daemon in background esegue periodicamente degli autocommit per salvare lo stato del vault.
2. **Esportazione Codice Pulito (Clean)**:
   - Per estrarre e condividere solo il software escludendo le note personali e le chiavi `.env`, esegui:
     ```bash
     python engine/main.py export-clean /percorso/di/destinazione
     ```
   - Questo comando legge i file tracciati da Git (ignorando quelli esclusi in `.gitignore`) e li copia nella nuova directory, pronta per essere pubblicata come open-source.

---

## 8. Risoluzione dei Problemi e Debugging

### 1. Test di Diagnostica Rapida
In caso di anomalie nelle email o nel sync Notion, esegui i test automatizzati:
```bash
.venv/bin/python -m pytest
```

### 2. Controllare i Servizi in Background
- **Su macOS**:
  ```bash
  launchctl list | grep secondbrain
  tail -f ~/Library/Logs/SecondBrain/*.log
  ```
- **Su Linux**:
  ```bash
  systemctl --user status secondbrain-dashboard.service
  journalctl --user -u secondbrain-dashboard.service -f
  ```

### 3. Connessione IMAP/SMTP Fallita
- Verifica i parametri inseriti in `.env`.
- Assicurati che le porte 465 (SMTP SSL) o 587 (SMTP STARTTLS) e 993 (IMAP SSL) non siano bloccate da firewall del server.
- Se usi Aruba, verifica di non aver abilitato restrizioni sugli IP nelle impostazioni di sicurezza dell'account email.
