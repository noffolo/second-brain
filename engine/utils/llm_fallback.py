import os
import json
import ssl
import urllib.request
import urllib.error
import asyncio
from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.types import CapabilitiesConfig

try:
    ssl_context = ssl._create_unverified_context()
except AttributeError:
    ssl_context = None

_original_gemini_key_pool = None

def resolve_gemini_key(model: str = None) -> str:
    """
    Risolve e ruota le chiavi API di Gemini da una lista separata da virgole in GEMINI_API_KEY.
    Memorizza la lista originale, filtra per chiavi non soggette a rate limit per il modello specificato,
    e seleziona a caso una delle chiavi sane, impostandola in os.environ["GEMINI_API_KEY"].
    """
    global _original_gemini_key_pool
    import random
    
    if _original_gemini_key_pool is None:
        _original_gemini_key_pool = os.getenv("GEMINI_API_KEY", "").strip()
        
    if not _original_gemini_key_pool:
        return ""
        
    if "," not in _original_gemini_key_pool:
        return _original_gemini_key_pool
        
    keys = [k.strip() for k in _original_gemini_key_pool.split(",") if k.strip()]
    if not keys:
        return ""
        
    # Filtra le chiavi che non sono in rate limit per il modello fornito
    available_keys = [k for k in keys if not is_key_rate_limited(k, model)]
    if not available_keys:
        # Se tutte le chiavi sono limitate, usa l'intero pool come ultima risorsa
        available_keys = keys
        
    selected_key = random.choice(available_keys)
    os.environ["GEMINI_API_KEY"] = selected_key
    return selected_key

def get_gemini_keys() -> list:
    """
    Ritorna la lista di tutte le chiavi Gemini configurate.
    """
    global _original_gemini_key_pool
    if _original_gemini_key_pool is None:
        _original_gemini_key_pool = os.getenv("GEMINI_API_KEY", "").strip()
        
    if not _original_gemini_key_pool:
        return []
        
    if "," not in _original_gemini_key_pool:
        return [_original_gemini_key_pool]
        
    return [k.strip() for k in _original_gemini_key_pool.split(",") if k.strip()]

# Circuit Breaker per i modelli che hanno esaurito la quota
RATE_LIMITS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".rate_limits.json")

def load_rate_limited_models() -> set:
    import time
    if not os.path.exists(RATE_LIMITS_FILE):
        return set()
    try:
        with open(RATE_LIMITS_FILE, "r") as f:
            data = json.load(f)
        now = time.time()
        active = set()
        for model, expiry in data.items():
            if now < expiry:
                active.add(model)
        return active
    except Exception as e:
        print(f"[Circuit Breaker] Errore di lettura file limitazioni: {e}")
        return set()

def save_rate_limited_model(model: str, duration_seconds: int = 1800):
    import time
    data = {}
    if os.path.exists(RATE_LIMITS_FILE):
        try:
            with open(RATE_LIMITS_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            pass
    
    now = time.time()
    clean_data = {}
    for m, expiry in data.items():
        if now < expiry:
            clean_data[m] = expiry
            
    clean_data[model] = now + duration_seconds
    
    try:
        with open(RATE_LIMITS_FILE, "w") as f:
            json.dump(clean_data, f)
        print(f"[Circuit Breaker] Modello {model} registrato come limitato fino a {time.strftime('%H:%M:%S', time.localtime(now + duration_seconds))}")
    except Exception as e:
        print(f"[Circuit Breaker] Errore di scrittura file limitazioni: {e}")

def is_key_rate_limited(api_key: str, model: str = None) -> bool:
    import time
    if not os.path.exists(RATE_LIMITS_FILE):
        return False
    try:
        with open(RATE_LIMITS_FILE, "r") as f:
            data = json.load(f)
        now = time.time()
        key_id = f"key_{api_key[:12]}"
        if model:
            key_id = f"key_{api_key[:12]}_{model}"
        expiry = data.get(key_id)
        if expiry and now < expiry:
            return True
    except Exception:
        pass
    return False

def save_rate_limited_key(api_key: str, model: str = None, duration_seconds: int = 300):
    import time
    data = {}
    if os.path.exists(RATE_LIMITS_FILE):
        try:
            with open(RATE_LIMITS_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            pass
    
    now = time.time()
    key_id = f"key_{api_key[:12]}"
    if model:
        key_id = f"key_{api_key[:12]}_{model}"
    data[key_id] = now + duration_seconds
    
    # Pulisci record scaduti
    clean_data = {}
    for k, expiry in data.items():
        if now < expiry:
            clean_data[k] = expiry
            
    try:
        with open(RATE_LIMITS_FILE, "w") as f:
            json.dump(clean_data, f)
        model_str = f" per modello {model}" if model else ""
        print(f"[Circuit Breaker] Chiave {api_key[:10]}...{model_str} registrata come limitata per {duration_seconds}s.", flush=True)
    except Exception as e:
        print(f"[Circuit Breaker] Errore di scrittura file limitazioni: {e}", flush=True)

async def call_openai_compatible_api(url: str, api_key: str, model: str, system_instructions: str, prompt: str, timeout: int = 25) -> str:
    """
    Effettua una chiamata HTTP asincrona (tramite thread pool) a un endpoint compatibile con OpenAI.
    """
    if system_instructions and not isinstance(system_instructions, str):
        system_instructions = getattr(system_instructions, "identity", getattr(system_instructions, "text", str(system_instructions)))
        
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_instructions},
            {"role": "user", "content": prompt}
        ]
    }

    
    # Forza il formato JSON se il prompt lo richiede (tipico per Ingest)
    if "json" in prompt.lower():
        # Molti provider moderni supportano response_format: json_object
        payload["response_format"] = {"type": "json_object"}

    data = json.dumps(payload).encode("utf-8")
    
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    loop = asyncio.get_running_loop()
    max_retries = 3
    base_delay = 4
    for attempt in range(max_retries + 1):
        try:
            def do_request():
                with urllib.request.urlopen(req, context=ssl_context, timeout=timeout) as response:
                    return response.read().decode("utf-8")
                    
            resp_body = await loop.run_in_executor(None, do_request)
            resp_json = json.loads(resp_body)
            return resp_json["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            err_content = e.read().decode("utf-8") if e.fp else str(e)
            is_rate_limit = (e.code == 429) or any(x in err_content.lower() for x in ["quota", "rate limit", "too many requests"])
            if is_rate_limit and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                print(f"HTTP Error {e.code} (Rate Limit) da {url}. Attesa di {delay} secondi (tentativo {attempt + 1}/{max_retries})...")
                await asyncio.sleep(delay)
            else:
                raise RuntimeError(f"HTTP Error {e.code}: {err_content}")
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = any(x in err_str for x in ["429", "quota", "rate limit", "too many requests"])
            if is_rate_limit and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                print(f"Errore {e} (Rate Limit) da {url}. Attesa di {delay} secondi (tentativo {attempt + 1}/{max_retries})...")
                await asyncio.sleep(delay)
            else:
                raise RuntimeError(f"{e}")

async def call_native_gemini_api(
    model: str, 
    api_key: str, 
    system_instructions: str, 
    prompt: str, 
    timeout: int = 25,
    use_vertex: bool = False,
    project: str = None,
    location: str = None
) -> str:
    """
    Invia una richiesta alle API di Google Gemini (via API Key o Vertex AI) usando l'SDK google-genai.
    """
    import asyncio
    from google.genai import Client, types
    from google.genai.errors import APIError

    if system_instructions and not isinstance(system_instructions, str):
        system_instructions = getattr(system_instructions, "identity", getattr(system_instructions, "text", str(system_instructions)))

    # Inizializza il client in base alla configurazione
    if use_vertex:
        client = Client(vertexai=True, project=project, location=location)
    else:
        if not api_key:
            raise ValueError("GEMINI_API_KEY non fornita.")
        client = Client(api_key=api_key)

    config = types.GenerateContentConfig(
        system_instruction=system_instructions,
        temperature=0.2,
    )
    if "json" in prompt.lower():
        config.response_mime_type = "application/json"

    # Tentativi con backoff esponenziale per errori transienti (non-429)
    max_retries = 3
    base_delay = 4
    for attempt in range(max_retries + 1):
        try:
            # Esegui la generazione asincrona con timeout
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config
                ),
                timeout=timeout
            )
            if response.text and response.text.strip():
                return response.text
            raise RuntimeError("Risposta vuota da Gemini API")
        except APIError as e:
            err_msg = e.message or ""
            is_rate_limit = (e.code == 429) or any(x in err_msg.lower() for x in ["quota", "rate limit", "too many requests", "resource_exhausted"])
            if is_rate_limit:
                # Per i limiti di quota solleviamo subito l'errore per attivare il circuit breaker e passare al fallback
                raise RuntimeError(f"HTTP Error 429 (Rate Limit): {err_msg}")
            elif attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                print(f"Errore API {e.code} da Gemini. Attesa di {delay}s (tentativo {attempt + 1}/{max_retries})...", flush=True)
                await asyncio.sleep(delay)
            else:
                raise RuntimeError(f"HTTP Error {e.code}: {err_msg}")
        except asyncio.TimeoutError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                print(f"Timeout durante la chiamata Gemini. Attesa di {delay}s...", flush=True)
                await asyncio.sleep(delay)
            else:
                raise RuntimeError("Chiamata a Gemini scaduta (Timeout)")
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = any(x in err_str for x in ["429", "quota", "rate limit", "too many requests", "resource_exhausted"])
            if is_rate_limit:
                raise RuntimeError(f"HTTP Error 429 (Rate Limit): {e}")
            elif attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                print(f"Errore {e} da Gemini API. Attesa di {delay}s...", flush=True)
                await asyncio.sleep(delay)
            else:
                raise RuntimeError(f"{e}")

def format_worst_case_fallback(prompt: str, errors: list) -> str:
    import re
    # Estrae la richiesta dell'utente
    question = ""
    question_match = re.search(r"La nuova richiesta dell'utente è la seguente:\s*(.*?)(?=\n\n---|\nRisultati della ricerca|$)", prompt, re.DOTALL)
    if question_match:
        question = question_match.group(1).strip()
    else:
        # Cerca dopo "Utente:" o righe simili
        lines = prompt.splitlines()
        for line in lines:
            if line.startswith("Utente:"):
                question = line.replace("Utente:", "", 1).strip()
                break
        if not question:
            question = "\n".join(lines[:3])

    # Estrae risultati della ricerca
    context = ""
    context_match = re.search(r"Risultati della ricerca nel vault:\s*(.*)", prompt, re.DOTALL)
    if context_match:
        context = context_match.group(1).strip()
    
    # Estrae statistiche
    stats = ""
    stats_match = re.search(r"--- Dati Statistici Aggregati Del Secondo Cervello ---\s*(.*?)(?=\nRisultati della ricerca|$)", prompt, re.DOTALL)
    if stats_match:
        stats = stats_match.group(1).strip()

    error_details = "\n".join([f"- {err}" for err in errors])
    
    response = (
        "⚠️ **[Servizio AI Temporaneamente Non Disponibile]**\n\n"
        "Gentile utente, tutti i provider di intelligenza artificiale configurati (Gemini, Vertex AI, DeepSeek, ecc.) "
        "sono attualmente congestionati, offline o hanno esaurito la quota giornaliera.\n\n"
        "Per garantirti comunque l'accesso alle tue informazioni, ti mostro di seguito i dati e i documenti "
        "estratti direttamente dal tuo Secondo Cervello (RAG locale) per la tua richiesta:\n\n"
    )
    
    if stats:
        response += "### 📊 Statistiche Rilevanti:\n"
        response += f"```\n{stats}\n```\n\n"
        
    if context:
        response += "### 📂 Documenti ed Estratti Rilevanti Trovati:\n\n"
        response += context + "\n"
    else:
        response += "*Nessun documento rilevante trovato nel vault locale per questa query.*\n\n"
        
    response += (
        "\n---\n"
        "**Dettagli degli errori di connessione riscontrati:**\n"
        f"```\n{error_details}\n```"
    )
    return response

async def call_llm_with_fallback(prompt: str, system_instructions: str, gemini_config: LocalAgentConfig) -> str:
    """
    Tenta di chiamare il modello Gemini di default (gemini-3.5-flash) tramite API REST nativa o Vertex AI.
    Se fallisce o è esaurita la quota, tenta con i modelli in cascata (gemini-2.5-flash -> gemini-3.1-flash-lite -> gemini-2.0-flash).
    Se tutti i modelli Gemini falliscono o sono congestionati, tenta la chiamata
    in cascata sui provider di fallback disponibili (OpenAI -> DeepSeek -> Together -> DashScope -> Zhipu -> Ollama Flat Cloud -> Ollama locale).
    """

    model_name = gemini_config.model
    if model_name.startswith("ollama"):
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip('/')
        ollama_model = "llama3"
        if "/" in model_name:
            ollama_model = model_name.split("/", 1)[1]
        elif os.getenv("OLLAMA_MODEL"):
            ollama_model = os.getenv("OLLAMA_MODEL")
            
        try:
            print(f"Invocazione Ollama locale ({ollama_model}) presso {ollama_host}...")
            return await call_openai_compatible_api(
                url=f"{ollama_host}/v1/chat/completions",
                api_key="ollama",
                model=ollama_model,
                system_instructions=system_instructions,
                prompt=prompt,
                timeout=90
            )
        except Exception as e:
            print(f"Ollama locale fallito: {e}. Tento con la catena standard.")

    if os.getenv("BYPASS_GEMINI") == "true":
        dashscope_key = os.getenv("DASHSCOPE_API_KEY")
        if dashscope_key and not dashscope_key.startswith("YOUR_"):
            try:
                print("Bypass Gemini: Invocazione DashScope (qwen-plus)...")
                return await call_openai_compatible_api(
                    url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                    api_key=dashscope_key,
                    model="qwen-plus",
                    system_instructions=system_instructions,
                    prompt=prompt
                )
            except Exception as e:
                print(f"DashScope fallito durante bypass: {e}. Tento OpenAI...")
                
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key and not openai_key.startswith("YOUR_"):
            try:
                print("Bypass Gemini: Invocazione OpenAI (gpt-4o-mini)...")
                return await call_openai_compatible_api(
                    url="https://api.openai.com/v1/chat/completions",
                    api_key=openai_key,
                    model="gpt-4o-mini",
                    system_instructions=system_instructions,
                    prompt=prompt
                )
            except Exception as e:
                print(f"OpenAI fallito durante bypass: {e}. Tento con la catena standard.")

    errors = []
    keys = get_gemini_keys()
    
    # Carica impostazioni Vertex se configurate in settings.md o gemini_config
    use_vertex = getattr(gemini_config, "vertex", False)
    vertex_project = getattr(gemini_config, "project", None)
    vertex_location = getattr(gemini_config, "location", "us-central1")
    
    if not use_vertex:
        try:
            from engine.utils.markdown import load_settings
            from engine.tools.vault_tools import get_vault_path
            settings = load_settings(get_vault_path())
            auth = settings.get("google_auth", {})
            if auth.get("use_vertex", False):
                use_vertex = True
                vertex_project = auth.get("project_id") or None
                vertex_location = auth.get("location", "us-central1")
        except Exception as e:
            print(f"[Fallback Settings] Fallito caricamento impostazioni Vertex: {e}")

    use_gemini = len(keys) > 0 or use_vertex
    
    if use_gemini:
        rate_limited_models = load_rate_limited_models()
        # 1a. Tentativo con Gemini Principale (es. gemini-3.5-flash)
        if gemini_config.model in rate_limited_models:
            print(f"Bypass Gemini Principale: {gemini_config.model} è contrassegnato in quota-limit.")
            errors.append(f"Gemini Principale ({gemini_config.model}): Saltato (in quota-limit).")
        else:
            # Prova prima via Vertex AI se abilitato
            if use_vertex:
                try:
                    print(f"Tentativo di elaborazione con Gemini ({gemini_config.model}) via Vertex AI...")
                    resp_text = await call_native_gemini_api(
                        model=gemini_config.model,
                        api_key=None,
                        system_instructions=gemini_config.system_instructions,
                        prompt=prompt,
                        timeout=15,
                        use_vertex=True,
                        project=vertex_project,
                        location=vertex_location
                    )
                    if resp_text and resp_text.strip():
                        return resp_text
                    raise RuntimeError("Risposta vuota da Vertex AI")
                except Exception as e:
                    errors.append(f"Vertex AI ({gemini_config.model}): {e}")
                    print(f"Vertex AI ({gemini_config.model}) fallito: {e}. Tento con le chiavi API...")

            # Prova poi via API keys in rotazione
            for current_key in keys:
                if is_key_rate_limited(current_key, gemini_config.model):
                    print(f"[Circuit Breaker] Saltata chiave {current_key[:10]}... (in blacklist su {gemini_config.model}).")
                    errors.append(f"Chiave {current_key[:10]}...: Saltata (in blacklist su {gemini_config.model}).")
                    continue
                os.environ["GEMINI_API_KEY"] = current_key
                try:
                    print(f"Tentativo di elaborazione con Gemini ({gemini_config.model}) via API key usando {current_key[:10]}...")
                    resp_text = await call_native_gemini_api(
                        model=gemini_config.model,
                        api_key=current_key,
                        system_instructions=gemini_config.system_instructions,
                        prompt=prompt,
                        timeout=15
                    )
                    if resp_text and resp_text.strip():
                        return resp_text
                    raise RuntimeError("Risposta vuota da Gemini API Key")
                except Exception as e:
                    errors.append(f"Gemini Principale ({gemini_config.model}) con chiave {current_key[:10]}: {e}")
                    err_str = str(e).lower()
                    is_rate_limit = any(x in err_str for x in ["429", "resource_exhausted", "quota", "rate limit", "too many requests", "vuota", "empty"])
                    if is_rate_limit:
                        print(f"Rate limit su {gemini_config.model} con chiave {current_key[:10]}. Inserisco in blacklist...")
                        save_rate_limited_key(current_key, gemini_config.model)
                    else:
                        print(f"Gemini API ({gemini_config.model}) fallita con chiave {current_key[:10]}: {e}. Tento successiva...")
            
            if keys and all(is_key_rate_limited(k, gemini_config.model) for k in keys):
                print(f"Tutte le chiavi in rate limit per {gemini_config.model}. Attivo circuit breaker.")
                save_rate_limited_model(gemini_config.model)
                        
        # 1b. Tentativo con modelli Gemini di fallback in cascata
        fallback_models = ["gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.0-flash"]
        for fallback_model in fallback_models:
            rate_limited_models = load_rate_limited_models()
            if fallback_model in rate_limited_models:
                errors.append(f"Gemini Fallback ({fallback_model}): Saltato (in quota-limit).")
                continue
            
            # Prova prima via Vertex AI se abilitato
            if use_vertex:
                try:
                    print(f"Tentativo di elaborazione con Gemini Fallback ({fallback_model}) via Vertex AI...")
                    resp_text = await call_native_gemini_api(
                        model=fallback_model,
                        api_key=None,
                        system_instructions=gemini_config.system_instructions,
                        prompt=prompt,
                        timeout=15,
                        use_vertex=True,
                        project=vertex_project,
                        location=vertex_location
                    )
                    if resp_text and resp_text.strip():
                        return resp_text
                    raise RuntimeError("Risposta vuota da Vertex AI")
                except Exception as e:
                    errors.append(f"Vertex AI Fallback ({fallback_model}): {e}")
                    print(f"Vertex AI Fallback ({fallback_model}) fallito: {e}. Tento con chiavi API...")

            # Prova poi via API keys in rotazione
            for current_key in keys:
                if is_key_rate_limited(current_key, fallback_model):
                    errors.append(f"Chiave {current_key[:10]}... (fallback): Saltata su {fallback_model}.")
                    continue
                os.environ["GEMINI_API_KEY"] = current_key
                try:
                    print(f"Tentativo di elaborazione con Gemini Fallback ({fallback_model}) usando chiave {current_key[:10]}...")
                    resp_text = await call_native_gemini_api(
                        model=fallback_model,
                        api_key=current_key,
                        system_instructions=gemini_config.system_instructions,
                        prompt=prompt,
                        timeout=25
                    )
                    if resp_text and resp_text.strip():
                        return resp_text
                    raise RuntimeError(f"Risposta vuota da Gemini API ({fallback_model})")
                except Exception as e2:
                    errors.append(f"Gemini Fallback ({fallback_model}) con chiave {current_key[:10]}: {e2}")
                    err_str2 = str(e2).lower()
                    is_rate_limit2 = any(x in err_str2 for x in ["429", "resource_exhausted", "quota", "rate limit", "too many requests", "vuota", "empty"])
                    if is_rate_limit2:
                        save_rate_limited_key(current_key, fallback_model)
                    else:
                        print(f"Gemini fallback ({fallback_model}) fallito con chiave {current_key[:10]}: {e2}.")
            
            if keys and all(is_key_rate_limited(k, fallback_model) for k in keys):
                save_rate_limited_model(fallback_model)
    else:
        errors.append("Gemini saltato: nessuna chiave o Vertex disabilitato.")

    # 2. Fallback su OpenAI (gpt-4o-mini)
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key and not openai_key.startswith("YOUR_"):
        try:
            print("Fallback: Invocazione OpenAI (gpt-4o-mini)...")
            return await call_openai_compatible_api(
                url="https://api.openai.com/v1/chat/completions",
                api_key=openai_key,
                model="gpt-4o-mini",
                system_instructions=system_instructions,
                prompt=prompt
            )
        except Exception as e:
            errors.append(f"OpenAI (gpt-4o-mini): {e}")
            print(f"OpenAI fallito: {e}. Tento provider successivo...")
  
    # 3. Fallback su DeepSeek (deepseek-chat)
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key and not deepseek_key.startswith("YOUR_"):
        try:
            print("Fallback: Invocazione DeepSeek (deepseek-chat)...")
            return await call_openai_compatible_api(
                url="https://api.deepseek.com/chat/completions",
                api_key=deepseek_key,
                model="deepseek-chat",
                system_instructions=system_instructions,
                prompt=prompt
            )
        except Exception as e:
            errors.append(f"DeepSeek (deepseek-chat): {e}")
            print(f"DeepSeek fallito: {e}. Tento provider successivo...")
  
    # 4. Fallback su Together AI (meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo)
    together_key = os.getenv("TOGETHER_API_KEY")
    if together_key and not together_key.startswith("YOUR_"):
        try:
            print("Fallback: Invocazione Together AI (meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo)...")
            return await call_openai_compatible_api(
                url="https://api.together.xyz/v1/chat/completions",
                api_key=together_key,
                model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
                system_instructions=system_instructions,
                prompt=prompt
            )
        except Exception as e:
            errors.append(f"Together (Meta-Llama-3.1-8B): {e}")
            print(f"Together AI fallito: {e}. Tento provider successivo...")
  
    # 5. Fallback su DashScope (qwen-plus)
    dashscope_key = os.getenv("DASHSCOPE_API_KEY")
    if dashscope_key and not dashscope_key.startswith("YOUR_"):
        try:
            print("Fallback: Invocazione DashScope (qwen-plus)...")
            return await call_openai_compatible_api(
                url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                api_key=dashscope_key,
                model="qwen-plus",
                system_instructions=system_instructions,
                prompt=prompt
            )
        except Exception as e:
            errors.append(f"DashScope (qwen-plus): {e}")
            print(f"DashScope fallito: {e}. Tento provider successivo...")
  
    # 6. Fallback su Zhipu AI (glm-4)
    zhipu_key = os.getenv("ZHIPU_API_KEY")
    if zhipu_key and not zhipu_key.startswith("YOUR_"):
        try:
            print("Fallback: Invocazione Zhipu AI (glm-4)...")
            return await call_openai_compatible_api(
                url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
                api_key=zhipu_key,
                model="glm-4",
                system_instructions=system_instructions,
                prompt=prompt
            )
        except Exception as e:
            errors.append(f"Zhipu (glm-4): {e}")
            print(f"Zhipu AI fallito: {e}.")

    # 6b. Fallback su Ollama Flat Cloud
    flat_cloud_key = os.getenv("OLLAMA_FLAT_CLOUD_KEY")
    flat_cloud_url = os.getenv("OLLAMA_FLAT_CLOUD_URL")
    if flat_cloud_key and flat_cloud_url:
        flat_cloud_model = os.getenv("OLLAMA_FLAT_CLOUD_MODEL", "qwen-plus")
        try:
            print(f"Fallback: Invocazione Ollama Flat Cloud ({flat_cloud_model}) presso {flat_cloud_url}...")
            return await call_openai_compatible_api(
                url=flat_cloud_url,
                api_key=flat_cloud_key,
                model=flat_cloud_model,
                system_instructions=system_instructions,
                prompt=prompt
            )
        except Exception as e:
            errors.append(f"Ollama Flat Cloud ({flat_cloud_model}): {e}")
            print(f"Ollama Flat Cloud fallito: {e}. Tento provider successivo...")
            
    # 7. Fallback finale su Ollama locale (se abilitato o se host configurato)
    if os.getenv("OLLAMA_ENABLED") == "true" or os.getenv("OLLAMA_HOST"):
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip('/')
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
        try:
            print(f"Fallback: Invocazione Ollama locale ({ollama_model})...")
            return await call_openai_compatible_api(
                url=f"{ollama_host}/v1/chat/completions",
                api_key="ollama",
                model=ollama_model,
                system_instructions=system_instructions,
                prompt=prompt,
                timeout=90
            )
        except Exception as e:
            errors.append(f"Ollama ({ollama_model}): {e}")
 
    error_summary = " | ".join(errors)
    print(f"[Fallback Outage] Tutti i provider LLM sono falliti. Dettagli: {error_summary}", flush=True)
    
    try:
        return format_worst_case_fallback(prompt, errors)
    except Exception as format_err:
        print(f"[Fallback Outage] Errore di formattazione worst-case: {format_err}", flush=True)
        raise RuntimeError(f"Tutti i provider di fallback sono falliti o non configurati. Dettagli: {error_summary}")


async def transcribe_audio_via_gemini(audio_base64: str, mime_type: str = "audio/ogg") -> str:
    """
    Invia un file audio codificato in base64 a Gemini per la trascrizione.
    Tenta prima con gemini-2.5-flash e i modelli in cascata, ruotando le chiavi disponibili.
    """
    import os
    import json
    import urllib.request
    import urllib.error
    
    keys = get_gemini_keys()
    if not keys:
        raise ValueError("GEMINI_API_KEY non impostata o non valida. Impossibile trascrivere il vocale.")

    # Modelli multimodali da tentare in cascata
    models = ["gemini-2.5-flash", "gemini-3.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    
    errors = []
    for model in models:
        for current_key in keys:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={current_key}"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": mime_type,
                                    "data": audio_base64
                                }
                            },
                            {
                                "text": (
                                    "Trascrivi fedelmente questo audio in lingua italiana. "
                                    "Restituisci solo ed esclusivamente la trascrizione letterale dell'audio, "
                                    "senza alcuna introduzione, commento, formattazione aggiuntiva, punteggiatura extra non pronunciata o spiegazione."
                                )
                            }
                        ]
                    }
                ]
            }
            
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            
            loop = asyncio.get_running_loop()
            try:
                print(f"[Telegram Audio] Tentativo di trascrizione audio con {model} usando chiave {current_key[:10]}...")
                def do_request():
                    with urllib.request.urlopen(req, context=ssl_context, timeout=60) as response:
                        return response.read().decode("utf-8")
                        
                resp_body = await loop.run_in_executor(None, do_request)
                resp_json = json.loads(resp_body)
                transcription = resp_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                if transcription:
                    return transcription
                else:
                    raise RuntimeError("Il modello ha restituito una risposta vuota.")
            except Exception as e:
                errors.append(f"{model} ({current_key[:10]}): {e}")
                print(f"[Telegram Audio] Errore trascrizione con {model} usando chiave {current_key[:10]}: {e}")
                
    raise RuntimeError(f"Tutti i modelli e le chiavi per la trascrizione sono falliti: {', '.join(errors)}")

