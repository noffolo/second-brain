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

## Guida alla configurazione del server remoto

La destinazione ideale per ospitare il Secondo Cervello è un server remoto sempre attivo. In questo scenario, puoi connettere l'applicazione locale Antigravity Desktop al server per interrogare il wiki in modo autonomo.

### 1. Avvio dei servizi sul server
Dopo aver installato il progetto sul server, abilita il demone per mantenere attivo il processo FastAPI (comprensivo dello scheduler interno e del server MCP):
```bash
make install-service
```
Questo comando configura ed avvia un servizio di sistema che controlla costantemente lo stato del pannello sulla porta `8000`.

### 2. Sicurezza e tunneling
Per evitare l'esposizione pubblica della porta `8000` sulla rete internet aperta, adotta una delle seguenti soluzioni:
* **VPN privata (consigliata)**: utilizza un servizio come Tailscale o WireGuard per inserire il server e il tuo computer locale all'interno della stessa rete privata protetta. In questo modo puoi accedere direttamente all'IP privato del server.
* **Proxy inverso HTTPS**: configura un server Nginx o Caddy sul server per esporre la dashboard tramite crittografia SSL con autenticazione di base o restrizioni IP.
* **Tunnel SSH temporaneo**: se desideri effettuare un test rapido, avvia un tunnel SSH dal tuo terminale locale:
  ```bash
  ssh -N -L 8000:127.0.0.1:8000 utente@ip-del-tuo-server
  ```

### 3. Connessione da Antigravity Desktop
1. Apri Antigravity Desktop sul tuo computer locale.
2. Accedi alla sezione delle impostazioni dedicata ai server MCP.
3. Aggiungi una nuova connessione di tipo **SSE** configurando i parametri come segue:
   * **Nome del server**: `secondo-cervello`
   * **URL SSE**: `http://<ip-del-tuo-server>:8000/mcp/sse` (oppure `https://<tuo-dominio>/mcp/sse` se protetto da SSL, o `http://127.0.0.1:8000/mcp/sse` se utilizzi il tunnel SSH).
4. In alternativa, modifica direttamente il file di configurazione `mcp_config.json` sul tuo computer locale:
   ```json
   {
     "mcpServers": {
       "secondo-cervello": {
         "url": "http://<ip-del-tuo-server>:8000/mcp/sse"
       }
     }
   }
   ```
5. Una volta connesso, gli agenti di Antigravity Desktop useranno automaticamente gli strumenti del vault (come `query_second_brain` e `search_vault`) per reperire e arricchire le informazioni del Secondo Cervello remoto.

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
