# Secondo cervello — base di conoscenza personale gestita da agenti AI

[![Stato dei test](https://img.shields.io/badge/test-38%20superati-brightgreen)](#)
[![Versione Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Licenza](https://img.shields.io/badge/licenza-GPL--3.0-green)](LICENSE)

Il secondo cervello organizza la conoscenza personale in un archivio locale strutturato in formato Markdown (compatibile con Obsidian). Il sistema automatizza l'importazione di note, compiti ed eventi da Notion, caselle di posta e-mail, calendari e articoli web, elaborando le informazioni tramite modelli di linguaggio per mappare concetti ed entità in una rete semantica coerente.

---

## Indice

1. [Come iniziare](#come-iniziare)
2. [Guida alla configurazione del server remoto](#guida-alla-configurazione-del-server-remoto)
3. [Funzionalità](#funzionalità)
4. [Documentazione aggiuntiva](#documentazione-aggiuntiva)
5. [Contribuire](#contribuire)
6. [Licenza](#licenza)
7. [Contatti / Riconoscimenti](#contatti--riconoscimenti)

---

## Come iniziare

### Prerequisiti
* Python 3.10 o versione successiva.
* Git per il tracciamento delle versioni.
* Un editor compatibile con Markdown (consigliato Obsidian per visualizzare il grafo semantico).

### Installazione
1. Clona questo repository all'interno della cartella dei tuoi progetti:
   ```bash
   git clone https://github.com/noffolo/second-brain.git
   cd second-brain
   ```
2. Configura l'ambiente virtuale, installa le dipendenze e genera il file delle impostazioni:
   ```bash
   make setup
   ```
3. Apri il file `.env` appena generato e inserisci le chiavi di autenticazione dei servizi esterni:
   * `GEMINI_API_KEY`: chiave per l'elaborazione tramite i modelli di linguaggio.
   * `NOTION_TOKEN`: token di integrazione per importare attività e agenda da Notion.
   * `TELEGRAM_BOT_TOKEN`: token del bot per abilitare il controllo tramite Telegram.
   * Parametri SMTP per l'invio delle e-mail di riepilogo giornaliere.

### Esempi d'uso
* **Avvio del pannello di controllo**:
  Avvia il server FastAPI locale per monitorare l'importazione dei file e lo stato dello scheduler universale:
  ```bash
  make dashboard
  ```
  Il pannello risponde all'indirizzo `http://127.0.0.1:8000`.
* **Interrogazione semantica del vault**:
  Invia una domanda per ottenere risposte basate sui tuoi documenti:
  ```bash
  python engine/main.py query "Quali sono le prossime scadenze del progetto Galattica?"
  ```
* **Distillazione di documenti**:
  Elabora un saggio, un articolo o un libro in formato PDF per estrarre concetti e creare note concetto:
  ```bash
  python engine/main.py distill percorso/del/documento.pdf it
  ```
* **Aggiunta di una nota di diario**:
  Registra rapidamente un evento nel diario:
  ```bash
  python engine/main.py journal "Definito il piano operativo per il nuovo progetto."
  ```

---

## Guida alla configurazione del server remoto (Linux)

La destinazione ideale per ospitare il Secondo Cervello è un server remoto Linux sempre attivo. Questo ti consente di interrogare il vault e far girare i servizi di sincronizzazione, briefing e dream mode in modo autonomo.

### 1. Completamento delle configurazioni (.env locale)
Prima di trasferire i file sul server, apri il file `.env` sul tuo computer locale e inserisci le credenziali reali dei servizi:

* **Telegram (Sicurezza)**: per impedire ad estranei di consultare o comandare il tuo Secondo Cervello, inserisci il tuo ID Telegram numerico (puoi ottenerlo inviando `/start` a [@userinfobot](https://t.me/userinfobot)):
  ```env
  TELEGRAM_ALLOWED_USERS=il_tuo_id_numerico
  ```
* **E-mail (SMTP in uscita per Briefing)**: per ricevere le mail di sintesi prima dei tuoi eventi (configura ad esempio tramite una Password dell'App di Gmail):
  ```env
  SMTP_SERVER=smtp.gmail.com
  SMTP_PORT=587
  SMTP_USERNAME=tua_email@gmail.com
  SMTP_PASSWORD=tua_password_di_app
  SMTP_FROM=tua_email@gmail.com
  SMTP_TO=tua_email_ricevente@gmail.com
  ```
* **E-mail (IMAP in entrata)**: per scaricare automaticamente le e-mail e gli allegati rilevanti da qualsiasi sistema operativo (Linux incluso):
  ```env
  IMAP_SERVER=imap.gmail.com
  IMAP_PORT=993
  IMAP_USERNAME=tua_email@gmail.com
  IMAP_PASSWORD=tua_password_di_app
  IMAP_MAILBOX=SecondBrain
  ```

### 2. Trasferimento dei file sul server
Il metodo consigliato per copiare la cartella locale del secondo cervello sul server remoto tramite SSH è `rsync`. Esegui questo comando dal terminale del tuo computer locale:
```bash
rsync -avz --exclude='.venv/' --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='build/' --exclude='*.egg-info/' ./ utente@ip-del-server:/home/utente/second_brain
```
*(Questo comando trasferirà anche il file `.env` configurato al passo precedente).*

### 3. Installazione e Setup sul server
Accedi al server remoto tramite SSH, entra nella cartella del progetto e configura l'ambiente virtuale:
```bash
ssh utente@ip-del-server
cd /home/utente/second_brain
make setup
```

### 4. Configurazione dei Servizi di Background (systemd)
Su Linux si utilizza `systemd` per mantenere attivi i servizi. Lo scheduler universale interno (sincronizzazione, riflessione, briefing e dream mode) è incorporato nel ciclo di vita della dashboard FastAPI. 
Dovrai quindi configurare solo due servizi di sistema.

#### A. Servizio Dashboard e Scheduler (`second-brain-dashboard.service`)
Crea il file del servizio:
```bash
sudo nano /etc/systemd/system/second-brain-dashboard.service
```
Aggiungi il seguente contenuto (adattando i percorsi dell'utente):
```ini
[Unit]
Description=Secondo Cervello - Dashboard, Scheduler e Server MCP
After=network.target

[Service]
Type=simple
User=utente
WorkingDirectory=/home/utente/second_brain
ExecStart=/home/utente/second_brain/.venv/bin/python -m uvicorn engine.dashboard:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

#### B. Servizio Bot Telegram (`second-brain-telegram.service`)
Crea il file del servizio:
```bash
sudo nano /etc/systemd/system/second-brain-telegram.service
```
Aggiungi il seguente contenuto:
```ini
[Unit]
Description=Secondo Cervello - Telegram Bot Daemon
After=network.target second-brain-dashboard.service

[Service]
Type=simple
User=utente
WorkingDirectory=/home/utente/second_brain
ExecStart=/home/utente/second_brain/.venv/bin/python engine/telegram_bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

#### C. Attivazione dei servizi
Ricarica i demoni di systemd, abilitali per l'esecuzione automatica all'avvio del server ed avviali:
```bash
sudo systemctl daemon-reload
sudo systemctl enable second-brain-dashboard
sudo systemctl enable second-brain-telegram
sudo systemctl start second-brain-dashboard
sudo systemctl start second-brain-telegram
```

### 5. Sicurezza e Connessione da Antigravity Desktop
Per motivi di sicurezza, la dashboard risponde solo all'indirizzo locale `127.0.0.1:8000`. Per connetterti dal tuo computer locale al server remoto, adotta una delle seguenti soluzioni:

* **VPN privata (Consigliata)**: Configura Tailscale o WireGuard sul server e sul tuo computer locale per collegarti direttamente all'IP privato del server. Cambia l'host di ascolto del servizio dashboard con l'IP Tailscale del server.
* **Tunnel SSH**: Avvia un tunnel dal tuo terminale locale per inoltrare la porta 8000 del server sul tuo computer locale:
  ```bash
  ssh -N -L 8000:127.0.0.1:8000 utente@ip-del-tuo-server
  ```
Una volta stabilita la connessione, aggiungi il server MCP all'interno del file di configurazione `mcp_config.json` di Antigravity Desktop o del tuo IDE:
```json
{
  "mcpServers": {
    "secondo-cervello": {
      "url": "http://127.0.0.1:8000/mcp/sse"
    }
  }
}
```


---

## Funzionalità

* **Integrazione con fonti eterogenee**: sincronizza dati da database Notion, calendari iCal, caselle e-mail (Apple Mail) e indirizzi web.
* **Mappatura semantica automatica**: traduce i testi grezzi in schede sintetiche per il wiki, creando collegamenti logici e relazioni tra concetti ed entità.
* **Scheduler universale asincrono**: esegue ciclicamente in background i compiti programmati (ingestione, riflessione settimanale, briefing e modalità sogno) leggendo i parametri configurati in `settings.md`.
* **Server MCP integrato**: espone un endpoint SSE per consentire l'interazione semantica a client esterni come Antigravity Desktop.
* **Controllo remoto tramite Telegram**: supporta l'avvio o l'arresto manuale delle procedure e l'inserimento rapido di note tramite comandi dedicati sulla chat del bot.

---

## Documentazione aggiuntiva

Per approfondire l'architettura tecnica dei moduli, il meccanismo di allineamento e commit automatico o la struttura del grafo semantico delle note, consulta il file di dettaglio tecnico [DOCS.md](DOCS.md).

---

## Contribuire

I contributi per arricchire il nucleo del Secondo Cervello sono benvenuti. Per inviare modifiche:
1. Consulta le regole di sviluppo in [CONTRIBUTING.md](CONTRIBUTING.md).
2. Rispetta rigorosamente le linee guida grammaticali e redazionali indicate in [buonsenso.md](buonsenso.md).
3. Apri una segnalazione o invia una proposta di modifica tramite pull request.

---

## Licenza

Questo progetto è distribuito sotto licenza **GNU GPL v3**. Leggi il file [LICENSE](LICENSE) per i termini completi del contratto.

---

## Contatti / Riconoscimenti

* Per segnalare bug o proporre nuove funzionalità, crea una segnalazione nell'apposita sezione delle issue su GitHub.
