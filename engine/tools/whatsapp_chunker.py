import os
import re
import glob

# Pattern standard: DD/MM/YY, HH:MM - 
# Pattern iOS: [DD/MM/YY, HH:MM:SS]
PATTERNS = [
    re.compile(r"^(\d{2})/(\d{2})/(\d{4}|\d{2}),\s*(\d{2}):(\d{2})\s*-\s*"),
    re.compile(r"^\[(\d{2})/(\d{2})/(\d{4}|\d{2}),\s*(\d{2}):(\d{2})(?::\d{2})?\]\s*")
]

def parse_line_date(line):
    for pattern in PATTERNS:
        m = pattern.match(line)
        if m:
            day = m.group(1)
            month = m.group(2)
            year_raw = m.group(3)
            year = f"20{year_raw}" if len(year_raw) == 2 else year_raw
            return f"{year}-{month}"
    return None

def chunk_whatsapp_files():
    # Percorsso della cartella raw/whatsapp/ relativa a questo file
    # engine/tools/whatsapp_chunker.py -> vault_path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    vault_path = os.path.abspath(os.path.join(current_dir, "..", ".."))
    whatsapp_dir = os.path.join(vault_path, "raw", "whatsapp")
    
    if not os.path.exists(whatsapp_dir):
        print("Cartella raw/whatsapp non trovata, salto il chunking.")
        return

    # Trova tutti i file .txt nella directory raw/whatsapp/
    txt_files = glob.glob(os.path.join(whatsapp_dir, "*.txt"))
    chunks_dir = os.path.join(whatsapp_dir, "chunks")
    os.makedirs(chunks_dir, exist_ok=True)

    for file_path in txt_files:
        basename = os.path.basename(file_path)
        group_name = os.path.splitext(basename)[0]
        print(f"Dividendo il file WhatsApp: {basename}...")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"Errore nella lettura di {basename}: {e}")
            continue

        monthly_groups = {}
        current_key = None
        current_chunk = []

        for line in lines:
            key = parse_line_date(line)
            if key:
                if current_key and current_chunk:
                    monthly_groups.setdefault(current_key, []).extend(current_chunk)
                current_key = key
                current_chunk = [line]
            else:
                if current_key:
                    current_chunk.append(line)
                else:
                    # Linee prima del primo messaggio (es. intestazioni)
                    # Le inseriamo in una chiave temporanea o le saltiamo
                    pass
        
        # Aggiungi l'ultimo blocco
        if current_key and current_chunk:
            monthly_groups.setdefault(current_key, []).extend(current_chunk)

        # Scrivi i file per ogni mese
        for key, msg_lines in monthly_groups.items():
            chunk_filename = f"{group_name}_{key}.txt"
            chunk_path = os.path.join(chunks_dir, chunk_filename)
            new_content = "".join(msg_lines)

            # Leggi contenuto esistente per evitare scritture inutili (preserva mtime)
            existing_content = ""
            if os.path.exists(chunk_path):
                try:
                    with open(chunk_path, "r", encoding="utf-8") as cf:
                        existing_content = cf.read()
                except Exception:
                    pass

            if existing_content != new_content:
                try:
                    with open(chunk_path, "w", encoding="utf-8") as cf:
                        cf.write(new_content)
                    print(f"  - Scritto chunk: {chunk_filename}")
                except Exception as e:
                    print(f"Errore nella scrittura del chunk {chunk_filename}: {e}")

if __name__ == "__main__":
    chunk_whatsapp_files()
