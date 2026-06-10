import asyncio
import os
from engine.utils.vector_db import get_vector_db
from engine.tools.embedder import chunk_text
from engine.query_agent import search_vault

def test_upsert():
    db = get_vector_db()
    text = "Il modello Gemini è fantastico per generare vettori. ChromaDB li salva in modo efficiente."
    chunks = chunk_text(text)
    print(f"Chunks generati: {len(chunks)}")
    db.upsert_chunks("wiki/test_file.md", "Test Vector", chunks)
    print("Upsert completato con successo.")

def test_search():
    print("Eseguo ricerca per 'come salvo i vettori?'...")
    results = search_vault("come salvo i vettori?")
    print(f"Risultati ricerca:\n{results}")

async def main():
    print("Inizio test vettoriale...")
    test_upsert()
    # Attesa per dar tempo al DB di aggiornarsi
    await asyncio.sleep(1)
    test_search()

if __name__ == "__main__":
    asyncio.run(main())
