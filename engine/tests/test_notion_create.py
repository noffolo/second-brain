import os
import shutil
import pytest
from engine.tools.vault_tools import get_vault_path, create_wiki_page_tool
from engine.tools.notion_tasks import create_notion_task

def test_create_wiki_page_tool():
    vault_path = get_vault_path()
    test_title = "Test Wiki Page Creation Tool 2026"
    test_category = "concepts"
    test_content = "Questo è il corpo della nota temporanea creata dal test."
    test_tags = ["test-tag-1", "test-tag-2"]
    
    expected_rel_path = f"wiki/{test_category}/Test Wiki Page Creation Tool 2026.md"
    expected_abs_path = os.path.join(vault_path, expected_rel_path)
    
    # Assicurati che non esista prima del test
    if os.path.exists(expected_abs_path):
        os.remove(expected_abs_path)
        
    try:
        msg = create_wiki_page_tool(test_title, test_category, test_content, test_tags)
        assert "creata con successo" in msg
        assert os.path.exists(expected_abs_path)
        
        with open(expected_abs_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        assert "Test Wiki Page Creation Tool 2026" in content
        assert "test-tag-1" in content
        assert "test-tag-2" in content
        assert test_content in content
        
        # Test di duplicato
        msg_dup = create_wiki_page_tool(test_title, test_category, test_content)
        assert "esiste già" in msg_dup
        
    finally:
        if os.path.exists(expected_abs_path):
            os.remove(expected_abs_path)

def test_create_notion_task_fallback():
    vault_path = get_vault_path()
    test_title = "Test Task Fallback Creation 2026"
    test_due_date = "2026-12-31"
    test_status = "To Do"
    test_category = "TestCategory"
    
    expected_rel_path = f"wiki/entities/{test_category}/Test Task Fallback Creation 2026.md"
    expected_abs_path = os.path.join(vault_path, expected_rel_path)
    
    # Assicurati che non esista prima del test
    if os.path.exists(expected_abs_path):
        os.remove(expected_abs_path)
        
    try:
        # Eseguiamo forzando il fallback (anche se Notion fosse configurato, verifichiamo la creazione del file locale)
        msg = create_notion_task(test_title, test_due_date, test_status, test_category)
        
        # Dovrebbe essere creato o localmente (in caso di API non collegate/fallite) o su Notion
        assert "creato" in msg.lower()
        assert os.path.exists(expected_abs_path)
        
        with open(expected_abs_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        assert "Test Task Fallback Creation 2026" in content
        assert "To Do" in content
        assert "2026-12-31" in content
        assert "microtheme" in content
        
    finally:
        if os.path.exists(expected_abs_path):
            os.remove(expected_abs_path)
        # Pulisce la cartella di test creata
        test_cat_dir = os.path.join(vault_path, "wiki", "entities", test_category)
        if os.path.exists(test_cat_dir):
            shutil.rmtree(test_cat_dir)

def test_create_notion_calendar_event_fallback():
    from engine.tools.notion_calendar import create_notion_calendar_event
    vault_path = get_vault_path()
    test_title = "Test Meeting Fallback Creation 2026"
    test_start_time = "2026-06-11T19:00:00"
    test_location = "Ufficio Test"
    
    expected_rel_path = "wiki/sources/Riunioni/Test Meeting Fallback Creation 2026.md"
    expected_abs_path = os.path.join(vault_path, expected_rel_path)
    
    if os.path.exists(expected_abs_path):
        os.remove(expected_abs_path)
        
    try:
        msg = create_notion_calendar_event(test_title, test_start_time, location=test_location)
        assert "creato" in msg.lower()
        assert os.path.exists(expected_abs_path)
        
        with open(expected_abs_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        assert "Test Meeting Fallback Creation 2026" in content
        assert "2026-06-11T19:00:00" in content
        assert "Ufficio Test" in content
        assert "meeting" in content
        
    finally:
        if os.path.exists(expected_abs_path):
            os.remove(expected_abs_path)
