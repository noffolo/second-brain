import os
import glob
from dotenv import load_dotenv
load_dotenv()
import asyncio
from engine.tools.vault_tools import get_vault_path
from engine.utils.vector_db import get_vector_db
from engine.tools.embedder import chunk_text

async def build_db():
    vault_path = get_vault_path()
    db = get_vector_db()
    
    # Folders to index
    folders_to_scan = [
        "wiki",
        "CRM",
        "Meetings",
        "People",
        "journal",
        "Microthemes"
    ]
    
    files_to_process = []
    
    for folder in folders_to_scan:
        abs_folder = os.path.join(vault_path, folder)
        if not os.path.exists(abs_folder):
            continue
            
        for root, dirs, files in os.walk(abs_folder):
            for file in files:
                if file.endswith(".md") and not file.startswith("."):
                    files_to_process.append(os.path.join(root, file))
                    
    print(f"Trovati {len(files_to_process)} file da indicizzare. Inizio indicizzazione massiva...")
    
    processed = 0
    errors = 0
    for file_path in files_to_process:
        rel_path = os.path.relpath(file_path, vault_path)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            title = os.path.basename(file_path).replace(".md", "")
            chunks = chunk_text(content)
            
            # Upsert
            db.upsert_chunks(rel_path, title, chunks)
            processed += 1
            if processed % 50 == 0:
                print(f"Progresso: {processed}/{len(files_to_process)} file elaborati...")
                
            # Rate limiting leggero per non intasare le API di Gemini
            await asyncio.sleep(0.5)
            
        except Exception as e:
            print(f"Errore durante l'elaborazione di {rel_path}: {e}")
            errors += 1
            
    print(f"\nIndicizzazione completata! {processed} file elaborati con successo, {errors} errori.")

if __name__ == "__main__":
    asyncio.run(build_db())
