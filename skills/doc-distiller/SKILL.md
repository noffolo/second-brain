---
name: doc-distiller
description: "Pipeline universale (Cross-Platform) per l'estrazione, sintesi e distillazione di documenti complessi. Converte libri, paper e saggi in formati .docx strutturati e genera artefatti di conoscenza (Skill Antigravity o schede Second Brain) su richiesta."
triggers: distilla, riassumi, sintetizza, distill, document summary, estrai conoscenza, second brain, crea skill
argument-hint: <path-to-document> [lang=it|en] [--mode research|standard]
---

# Mega-Skill Document Distiller — V1 (Universal)

Trasforma qualsiasi documento o libro in un saggio sintetico strutturato (.docx) ad alto valore analitico, isolando concetti chiave ed eliminando allucinazioni. Al termine del processo, offre la distillazione del testo in una Skill operativa o in formati di knowledge management.

## Requisiti di Sistema
- **Python 3.10+** (Cross-platform: macOS, Linux, Windows)
- **Local/Cloud LLM**: Accesso a Ollama (`deepseek-v4-flash:cloud` o equivalenti locali)
