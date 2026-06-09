import os
import shutil
import pytest
from engine.tools.vault_tools import search_wiki, get_vault_path

def test_search_wiki_integration():
    vault_path = get_vault_path()
    
    # Create a temporary test file inside wiki/concepts/ (allowed search dir)
    test_dir = os.path.join(vault_path, "wiki", "concepts", "test_temp_folder")
    os.makedirs(test_dir, exist_ok=True)
    
    test_file_path = os.path.join(test_dir, "test_search_optimization_node.md")
    
    content = """---
title: "Test Search Optimization Node"
type: "concept"
---

Questo è un file temporaneo di test per verificare che la ricerca git grep funzioni velocemente e correttamente.
ParolaChiaveUnicaDiTest2026
"""
    
    try:
        with open(test_file_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        # Run search
        results = search_wiki("ParolaChiaveUnicaDiTest2026")
        
        # Verify
        assert len(results) > 0
        
        found = False
        for r in results:
            if "test_search_optimization_node" in r["title"].lower():
                found = True
                assert "test_search_optimization_node" in r["path"]
                assert "test_search_optimization" in r["snippet"] or "ParolaChiave" in r["snippet"]
                
        assert found, f"File not found in search results: {results}"
        
    finally:
        # Clean up
        if os.path.exists(test_file_path):
            os.remove(test_file_path)
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
