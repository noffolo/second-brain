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

async def call_native_gemini_api(model: str, api_key: str, system_instructions: str, prompt: str, timeout: int = 25) -> str:
    """
    Invia una richiesta HTTP POST diretta alle API REST di Google Gemini (senza passare per l'SDK).
    Questo evita conflitti di autorizzazioni degli strumenti (tool declarations) e fornisce codici 429 immediati.
    """
    if system_instructions and not isinstance(system_instructions, str):
        system_instructions = getattr(system_instructions, "identity", getattr(system_instructions, "text", str(system_instructions)))
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }
    if system_instructions:
        payload["systemInstruction"] = {
            "parts": [
                {"text": system_instructions}
            ]
        }
        
    # Forza il formato JSON se il prompt lo richiede
    if "json" in prompt.lower():
        payload["generationConfig"] = {
            "responseMimeType": "application/json"
        }
 
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    
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
            return resp_json["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            err_content = e.read().decode("utf-8") if e.fp else str(e)
            is_rate_limit = (e.code == 429) or any(x in err_content.lower() for x in ["quota", "rate limit", "too many requests"])
            if is_rate_limit:
                # Per i limiti di quota sui modelli gratuiti, solleviamo subito l'errore per attivare il circuit breaker
                raise RuntimeError(f"HTTP Error 429 (Rate Limit): {err_content}")
            elif attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                print(f"HTTP Error {e.code} da Gemini API. Attesa di {delay} secondi (tentativo {attempt + 1}/{max_retries})...")
                await asyncio.sleep(delay)
            else:
                raise RuntimeError(f"HTTP Error {e.code}: {err_content}")
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = any(x in err_str for x in ["429", "quota", "rate limit", "too many requests"])
            if is_rate_limit:
                raise RuntimeError(f"Error 429: {e}")
            elif attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                print(f"Errore {e} da Gemini API. Attesa di {delay} secondi (tentativo {attempt + 1}/{max_retries})...")
                await asyncio.sleep(delay)
            else:
                raise RuntimeError(f"{e}")

async def call_llm_with_fallback(prompt: str, system_instructions: str, gemini_config: LocalAgentConfig) -> str:
    """
    Tenta di chiamare il modello Gemini di default (gemini-3.5-flash) tramite API REST nativa.
    Se fallisce o è esaurita la quota, tenta con i modelli in cascata (gemini-2.5-flash -> gemini-3.1-flash-lite -> gemini-2.0-flash).
    Se tutti i modelli Gemini falliscono o sono congestionati, tenta la chiamata
    in cascata sui provider di fallback disponibili (OpenAI -> DeepSeek -> Together -> DashScope -> Zhipu).
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
    use_gemini = len(keys) > 0 or (hasattr(gemini_config, "vertex") and gemini_config.vertex)
    
    if use_gemini:
        rate_limited_models = load_rate_limited_models()
        # 1a. Tentativo con Gemini Principale (da settings.md, es. gemini-3.5-flash)
        if gemini_config.model in rate_limited_models:
            print(f"Bypass Gemini Principale: {gemini_config.model} è contrassegnato in quota-limit nel file .rate_limits.json.")
            errors.append(f"Gemini Principale ({gemini_config.model}): Saltato (in quota-limit).")
        else:
            for current_key in keys:
                if is_key_rate_limited(current_key, gemini_config.model):
                    print(f"[Circuit Breaker] Saltata chiave {current_key[:10]}... (in blacklist per 429 su {gemini_config.model}).")
                    errors.append(f"Chiave {current_key[:10]}...: Saltata (in blacklist per 429 su {gemini_config.model}).")
                    continue
                os.environ["GEMINI_API_KEY"] = current_key
                try:
                    print(f"Tentativo di elaborazione con Gemini ({gemini_config.model}) via API REST nativa usando chiave {current_key[:10]}...")
                    resp_text = await call_native_gemini_api(
                        model=gemini_config.model,
                        api_key=current_key,
                        system_instructions=gemini_config.system_instructions,
                        prompt=prompt,
                        timeout=12
                    )
                    if resp_text and resp_text.strip() != "":
                        return resp_text
                    raise RuntimeError("Risposta vuota da Gemini API")
                except Exception as e:
                    errors.append(f"Gemini Principale ({gemini_config.model}) con chiave {current_key[:10]}: {e}")
                    err_str = str(e).lower()
                    is_rate_limit = any(x in err_str for x in ["429", "resource_exhausted", "quota", "rate limit", "too many requests", "vuota", "empty"])
                    if is_rate_limit:
                        print(f"Rilevato limite di quota/frequenza (429) per {gemini_config.model} con chiave {current_key[:10]}. Inserisco in blacklist per 5 minuti...")
                        save_rate_limited_key(current_key, gemini_config.model)
                    else:
                        err_msg = str(e)
                        print(f"Gemini API ({gemini_config.model}) fallita con chiave {current_key[:10]} ({err_msg[:80]}...). Tento chiave successiva...")
            
            if keys and all(is_key_rate_limited(k, gemini_config.model) for k in keys):
                print(f"Tutte le chiavi hanno fallito/sono in rate limit per {gemini_config.model}. Attivo il circuit breaker per questo modello.")
                save_rate_limited_model(gemini_config.model)
                        
        # 1b. Tentativo con modelli Gemini di fallback in cascata (gemini-2.5-flash, gemini-3.1-flash-lite, gemini-2.0-flash)
        fallback_models = ["gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.0-flash"]
        for fallback_model in fallback_models:
            # Ricarichiamo le limitazioni per rilevare modifiche in tempo reale fatte da altri thread/processi
            rate_limited_models = load_rate_limited_models()
            if fallback_model in rate_limited_models:
                print(f"Bypass fallback: {fallback_model} è contrassegnato in quota-limit nel file .rate_limits.json.")
                errors.append(f"Gemini Fallback ({fallback_model}): Saltato (in quota-limit).")
                continue
            
            for current_key in keys:
                if is_key_rate_limited(current_key, fallback_model):
                    print(f"[Circuit Breaker] Saltata chiave {current_key[:10]}... per fallback {fallback_model} (in blacklist per 429).")
                    errors.append(f"Chiave {current_key[:10]}... (fallback): Saltata (in blacklist per 429 su {fallback_model}).")
                    continue
                os.environ["GEMINI_API_KEY"] = current_key
                try:
                    print(f"Tentativo di elaborazione con Gemini di Fallback ({fallback_model}) via API REST nativa usando chiave {current_key[:10]}...")
                    resp_text = await call_native_gemini_api(
                        model=fallback_model,
                        api_key=current_key,
                        system_instructions=gemini_config.system_instructions,
                        prompt=prompt,
                        timeout=25
                    )
                    if resp_text and resp_text.strip() != "":
                        return resp_text
                    raise RuntimeError(f"Risposta vuota da Gemini API ({fallback_model})")
                except Exception as e2:
                    errors.append(f"Gemini Fallback ({fallback_model}) con chiave {current_key[:10]}: {e2}")
                    err_str2 = str(e2).lower()
                    is_rate_limit2 = any(x in err_str2 for x in ["429", "resource_exhausted", "quota", "rate limit", "too many requests", "vuota", "empty"])
                    if is_rate_limit2:
                        print(f"Rilevato limite di quota/frequenza (429) per fallback {fallback_model} con chiave {current_key[:10]}. Inserisco in blacklist per 5 minuti...")
                        save_rate_limited_key(current_key, fallback_model)
                    else:
                        print(f"Gemini fallback ({fallback_model}) fallito con chiave {current_key[:10]}: {e2}. Tento chiave successiva...")
            
            if keys and all(is_key_rate_limited(k, fallback_model) for k in keys):
                print(f"Tutte le chiavi hanno fallito/sono in rate limit per {fallback_model}. Attivo il circuit breaker per questo modello.")
                save_rate_limited_model(fallback_model)
    else:
        errors.append("Gemini saltato: chiavi non valide o vuote in GEMINI_API_KEY e Vertex disabilitato.")

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

