import os
import shutil
import pytest
import asyncio
from engine.tools.vault_tools import get_vault_path
from engine.query_agent import hybrid_search_vault_func, search_internet

@pytest.mark.asyncio
async def test_hybrid_search_raw_folder_and_scoring():
    vault_path = get_vault_path()
    
    # Crea una mail temporanea nella cartella raw/mail/
    test_dir = os.path.join(vault_path, "raw", "mail", "test_temp_mail")
    os.makedirs(test_dir, exist_ok=True)
    
    test_file_path = os.path.join(test_dir, "test_raw_email_12345.md")
    
    content = """---
subject: "Oggetto di test della mail grezza"
from: "mittente@test.com"
---
Ecco il testo della mail che contiene la parola chiave unica LetiziaGuglielmiTest2026.
Questa informazione si trova solo in questo file raw.
"""
    try:
        with open(test_file_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        # Esegue la ricerca ibrida
        results = await hybrid_search_vault_func("LetiziaGuglielmiTest2026", limit=5)
        
        # Verifica che il file sia stato trovato
        assert len(results) > 0
        found = False
        for r in results:
            if "test_raw_email_12345" in r["title"].lower() or "test_raw_email_12345" in r["path"]:
                found = True
                assert "raw/mail" in r["path"]
                assert "LetiziaGuglielmiTest2026" in r["snippet"]
                
        assert found, f"Il file in raw/ non è stato trovato: {results}"
        
    finally:
        # Pulisce i file temporanei
        if os.path.exists(test_file_path):
            os.remove(test_file_path)
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)

def test_search_internet_duckduckgo():
    # Verifica che la ricerca internet restituisca risultati
    res = search_internet("Python programming language")
    
    assert "--- RISULTATI DELLA RICERCA INTERNET ---" in res
    assert "Python" in res
