import os
import chromadb
from engine.tools.vault_tools import get_vault_path
from engine.tools.embedder import get_embedding, get_query_embedding, get_embeddings

class VectorDB:
    def __init__(self, collection_name="second_brain_docs"):
        self.vault_path = get_vault_path()
        self.db_path = os.path.join(self.vault_path, "vault", "vector_store")
        os.makedirs(self.db_path, exist_ok=True)
        # Initialize persistent client
        self.client = chromadb.PersistentClient(path=self.db_path)
        self.collection = self.client.get_or_create_collection(name=collection_name)

    def upsert_chunks(self, path: str, title: str, chunks: list[str]):
        """
        Salva i chunk vettorializzati nel database, rimuovendo le versioni precedenti dello stesso file.
        """
        if not chunks:
            return
            
        # Pulisci i vecchi chunk di questo file per evitare duplicati
        try:
            self.collection.delete(where={"path": path})
        except Exception:
            pass # Ignora se non esiste
        
        ids = []
        embeddings = []
        documents = []
        metadatas = []
        
        try:
            embs = get_embeddings(chunks)
        except Exception as e:
            print(f"[VectorDB] Errore nell'embedding batch dei chunk per {path}: {e}")
            return
            
        for i, chunk in enumerate(chunks):
            emb = embs[i] if i < len(embs) else None
            if not emb:
                continue
            ids.append(f"{path}_{i}")
            embeddings.append(emb)
            documents.append(chunk)
            metadatas.append({
                "path": path,
                "title": title,
                "chunk_index": i
            })
                
        if ids:
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )

    def search_similar(self, query: str, limit: int = 10) -> list[dict]:
        """
        Cerca i frammenti più simili alla query usando la Cosine Similarity (default Chroma).
        """
        try:
            query_emb = get_query_embedding(query)
            if not query_emb:
                return []
                
            results = self.collection.query(
                query_embeddings=[query_emb],
                n_results=limit
            )
            
            output = []
            if results['documents'] and len(results['documents']) > 0:
                docs = results['documents'][0]
                metas = results['metadatas'][0]
                distances = results['distances'][0]
                
                for i in range(len(docs)):
                    output.append({
                        "path": metas[i]["path"],
                        "title": metas[i]["title"],
                        "snippet": docs[i],
                        "distance": distances[i] # In chroma default (l2), lower is better
                    })
            return output
        except Exception as e:
            print(f"[VectorDB] Errore search_similar per query '{query}': {e}")
            return []

# Singleton instance
_vector_db_instance = None

def get_vector_db() -> VectorDB:
    global _vector_db_instance
    if _vector_db_instance is None:
        _vector_db_instance = VectorDB()
    return _vector_db_instance
