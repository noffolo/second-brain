import os
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from engine.watcher import watch_vault_changes

@pytest.mark.asyncio
async def test_watch_vault_changes_ignores_non_relevant():
    mock_manager = MagicMock()
    mock_manager.is_running.return_value = False
    mock_manager.start = AsyncMock(return_value=True)
    
    mock_changes = [
        ("added", "/path/to/vault/raw/mail_attachments/photo.jpg"),
        ("modified", "/path/to/vault/raw/.DS_Store"),
        ("modified", "/path/to/vault/raw/test.gitkeep"),
    ]
    
    async def mock_awatch(*args, **kwargs):
        yield mock_changes
        
    with patch("engine.watcher.awatch", side_effect=mock_awatch):
        with patch("engine.watcher.get_vault_path", return_value="/path/to/vault"):
            with patch("engine.watcher.os.makedirs") as mock_makedirs:
                watcher_task = asyncio.create_task(watch_vault_changes(mock_manager))
                await asyncio.sleep(0.1)
                watcher_task.cancel()
                try:
                    await watcher_task
                except asyncio.CancelledError:
                    pass
                
    mock_manager.start.assert_not_called()

@pytest.mark.asyncio
async def test_watch_vault_changes_triggers_relevant():
    mock_manager = MagicMock()
    mock_manager.is_running.return_value = False
    mock_manager.start = AsyncMock(return_value=True)
    
    mock_changes = [
        ("modified", "/path/to/vault/raw/manual/test.md"),
    ]
    
    async def mock_awatch(*args, **kwargs):
        yield mock_changes
        while True:
            await asyncio.sleep(1)
        
    with patch("engine.watcher.awatch", side_effect=mock_awatch):
        with patch("engine.watcher.get_vault_path", return_value="/path/to/vault"):
            with patch("engine.watcher.os.makedirs") as mock_makedirs:
                watcher_task = asyncio.create_task(watch_vault_changes(mock_manager))
                # Aspetta che scatti il debounce di 3 secondi
                await asyncio.sleep(3.5)
                watcher_task.cancel()
                try:
                    await watcher_task
                except asyncio.CancelledError:
                    pass
                
    mock_manager.start.assert_called_once()
