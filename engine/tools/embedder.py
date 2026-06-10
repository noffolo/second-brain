import os
from google import genai
from typing import List
from engine.utils.markdown import load_settings
from engine.tools.vault_tools import get_vault_path

EMBEDDING_MODEL = "gemini-embedding-2"

def get_client() -> genai.Client:
    vault_path = get_vault_path()
    settings = load_settings(vault_path)
    auth = settings.get("google_auth", {})
    
    if auth.get("use_vertex", False):
        project = auth.get("project_id")
        location = auth.get("location", "us-central1")
        if not project:
            raise ValueError("project_id mancante in settings.md per l'uso di Vertex AI.")
        return genai.Client(vertexai=True, project=project, location=location)
    else:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key or api_key == "dummy-key":
            raise ValueError("GEMINI_API_KEY is not set correctly. Usa Vertex AI oppure inserisci una chiave.")
        return genai.Client(api_key=api_key)

def get_embedding(text: str) -> List[float]:
    if not text.strip():
        return []
    client = get_client()
    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
    )
    return result.embeddings[0].values

def get_query_embedding(query: str) -> List[float]:
    if not query.strip():
        return []
    client = get_client()
    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=query,
    )
    return result.embeddings[0].values

def chunk_text(text: str, max_chars: int = 1000, overlap: int = 200) -> List[str]:
    """
    Divide il testo in chunk sovrapposti, utile per il RAG.
    Ignora il frontmatter YAML iniziale se presente.
    """
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2].strip()
            
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        # Cerca un punto logico di interruzione (capoverso o punto)
        if end < len(text):
            break_idx = text.rfind('\n', start, end)
            if break_idx == -1 or break_idx <= start + overlap:
                break_idx = text.rfind('. ', start, end)
                if break_idx == -1 or break_idx <= start + overlap:
                    break_idx = end
            else:
                break_idx += 1 # Include il newline
        else:
            break_idx = len(text)
            
        chunk = text[start:break_idx].strip()
        if chunk:
            chunks.append(chunk)
            
        # Avanza sovrapponendo per preservare il contesto
        start = break_idx - overlap
        if start < 0 or break_idx == len(text):
            break
            
    return chunks
