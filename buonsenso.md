---
name: buonsenso
description: >-
  Linee guida per la riscrittura, la sanificazione editoriale e l'allineamento semantico delle note all'interno del secondo cervello.
tags:
  - buonsenso
  - style-guide
related:
  - '[[wiki/sources/Esempio/PD/appunti_riunione_pd|Appunti riunione PD]]'
  - '[[wiki/concepts/Esempio/Framing dei dati nella propaganda politica|Framing dei dati nella propaganda politica]]'
updated_at: '2026-06-07 13:53:00'
created_at: '2026-06-07 11:45:00'
---
# Buonsenso — linee guida redazionali ed editoriali per il secondo cervello

Questo documento definisce le linee guida operative che l'assistente AI deve applicare autonomamente durante l'analisi, la scrittura e la modifica delle note nel vault, al fine di garantire la qualità linguistica e l'integrità strutturale della conoscenza condivisa.

## Linee guida editoriali

### 1. Capitalizzazione dei titoli
Nei titoli e nelle intestazioni in lingua italiana, applicare le regole grammaticali nazionali:
* Utilizzare la lettera maiuscola esclusivamente per la prima parola del titolo e per i nomi propri.
* Evitare la capitalizzazione in stile anglosassone (maiuscola per ogni parola), che costituisce un errore grave.

### 2. Rimozione dei costrutti retorici tipici dell'AI
Evitare l'uso di strutture retoriche ridondanti o abusate dai modelli generativi, come:
* La struttura duale *"non X, ma Y"* (es. *"non propone forniture isolate, ma si offre come..."*). Sostituirla con affermazioni dirette, attive e propositive (es. *"propone una partnership, superando la logica di..."*).
* La struttura *"non solo X, ma anche Y"*. Risolvere descrivendo le caratteristiche in modo lineare e assertivo.

### 3. Traduzione strategica e de-gergonizzazione
Quando si rielaborano note o proposte rivolte a interlocutori esterni non tecnici (es. partiti politici, associazioni o enti territoriali):
* Tradurre i termini tecnici specialistici (es. *moduli MCP*, *middleware*, *tipografia molecolare*) in concetti basati sul valore e sull'utilità pratica (es. *autonomia visiva*, *standardizzazione dei flussi*, *semplificazione operativa*).
* Spiegare con chiarezza **cosa cambia** e **come cambia** l'operatività reale con l'introduzione di strumenti complessi (come i sistemi a intelligenza artificiale o il *second brain*).

---

## Integrità e allineamento del vault

### 1. Creazione e aggiornamento dei concetti
* Ogni volta che viene introdotta un'idea o un tema rilevante in una nota di lavoro, verificare se esiste già una nota di concetto in `wiki/concepts/`.
* Creare una nuova nota di concetto in caso di assenza, o arricchire quella esistente integrando i nuovi spunti senza sovrascrivere o cancellare le informazioni precedenti.

### 2. Linking semantico e metadati
* Collegare le note nel frontmatter tramite relazioni esplicite sotto la chiave `related` utilizzando i Wikilink (es. `- '[[wiki/concepts/...|Nome Concetto]]'`).
* Aggiornare sempre il campo `updated_at` nei metadati YAML del file modificato.

### 3. Registrazione e verifica
* Registrare sinteticamente ogni creazione o modifica rilevante nell'indice generale del vault (`index.md`) e in coda al registro delle attività (`log.md`).
* Eseguire la suite di test locali (es. `make test`) per garantire che i collegamenti introdotti non siano interrotti e che la sintassi di tutte le note sia corretta.

### 4. Principio di atomicità (note autoconsistenti)
* Scrivere le note concetto in modo che siano **atomiche** (focalizzate su un unico argomento o idea chiara).
* Il titolo della nota deve rappresentare un "pensiero compiuto" o un'entità ben definita, piuttosto che una categoria generica (es. preferire `Circoli PD come spazi di comunità e mutualismo` rispetto a `Circoli PD`).

### 5. Organizzazione bottom-up ed emergenza della struttura
* Evitare l'over-tagging: utilizzare i tag esclusivamente per definire lo *stato* o la *tipologia* della nota (es. `#status/draft`, `#status/complete`, `#type/concept`, `#type/meeting`), e non per categorizzare temi generici.
* Per collegare i temi, fare affidamento sui collegamenti bidirezionali (`[[Wikilink]]`) e sulle mappe dei contenuti (MOC, come `index.md`), lasciando che la struttura del vault emerga dal basso in base alle reali relazioni tra i dati.
* Evitare la sovrastrutturazione preventiva (struttura "just in case"): non creare directory o file basandosi su relazioni potenziali o ipotetiche prima di aver effettivamente accumulato il materiale.

### 6. Pulizia dei file e allegati
* Archiviare tutti i file grezzi, le immagini, i PDF e i materiali non modificabili esclusivamente all'interno delle cartelle dedicate (come `raw/` o `attachments/`), evitando di inquinare le cartelle attive del wiki con elementi non strutturati.

