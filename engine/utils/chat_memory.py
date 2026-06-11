import os
import json
from typing import List, Dict

class ChatMemory:
    def __init__(self, storage_path: str, max_messages: int = 6):
        self.storage_path = storage_path
        self.max_messages = max_messages
        self.memory: Dict[str, List[Dict[str, str]]] = self._load()

    def _load(self) -> Dict[str, List[Dict[str, str]]]:
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading chat memory: {e}")
        return {}

    def _save(self):
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving chat memory: {e}")

    def add_message(self, chat_id: str, role: str, content: str):
        chat_id_str = str(chat_id)
        if chat_id_str not in self.memory:
            self.memory[chat_id_str] = []
            
        self.memory[chat_id_str].append({"role": role, "content": content})
        
        # Mantieni solo gli ultimi max_messages (che equivale a max_messages/2 scambi)
        if len(self.memory[chat_id_str]) > self.max_messages:
            self.memory[chat_id_str] = self.memory[chat_id_str][-self.max_messages:]
            
        self._save()

    def get_history(self, chat_id: str) -> List[Dict[str, str]]:
        return self.memory.get(str(chat_id), [])

    def get_conversation_id(self, chat_id: str) -> str:
        import uuid
        chat_id_str = str(chat_id)
        if "__conversation_ids__" not in self.memory:
            self.memory["__conversation_ids__"] = {}
            
        conv_ids = self.memory["__conversation_ids__"]
        if chat_id_str not in conv_ids:
            conv_ids[chat_id_str] = str(uuid.uuid4())
            self._save()
            
        return conv_ids[chat_id_str]

    def clear_history(self, chat_id: str):
        import uuid
        chat_id_str = str(chat_id)
        if chat_id_str in self.memory:
            self.memory[chat_id_str] = []
            
        if "__conversation_ids__" not in self.memory:
            self.memory["__conversation_ids__"] = {}
            
        # Rigeneriamo l'UUID nativo dell'SDK
        self.memory["__conversation_ids__"][chat_id_str] = str(uuid.uuid4())
        self._save()
