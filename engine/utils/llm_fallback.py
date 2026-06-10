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

async def call_openai_compatible_api(url: str, api_key: str, model: str, system_instructions: str, prompt: str) -> str:
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
                with urllib.request.urlopen(req, context=ssl_context, timeout=90) as response:
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

async def call_native_gemini_api(model: str, api_key: str, system_instructions: str, prompt: str) -> str:
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
                with urllib.request.urlopen(req, context=ssl_context, timeout=90) as response:
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
    import os
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    is_gemini_key_valid = gemini_key and gemini_key != "dummy-key" and not gemini_key.startswith("YOUR_")
    use_gemini = is_gemini_key_valid or (hasattr(gemini_config, "vertex") and gemini_config.vertex)

    model_name = gemini_config.model
    if model_name.startswith("ollama") or os.getenv("OLLAMA_ENABLED") == "true":
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
                prompt=prompt
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
    
    if use_gemini:
        rate_limited_models = load_rate_limited_models()
        # 1a. Tentativo con Gemini Principale (da settings.md, es. gemini-3.5-flash)
        if gemini_config.model in rate_limited_models:
            print(f"Bypass Gemini Principale: {gemini_config.model} è contrassegnato in quota-limit nel file .rate_limits.json.")
            errors.append(f"Gemini Principale ({gemini_config.model}): Saltato (in quota-limit).")
        else:
            try:
                print(f"Tentativo di elaborazione con Gemini ({gemini_config.model}) via API REST nativa...")
                resp_text = await call_native_gemini_api(
                    model=gemini_config.model,
                    api_key=gemini_key,
                    system_instructions=gemini_config.system_instructions,
                    prompt=prompt
                )
                if resp_text and resp_text.strip() != "":
                    return resp_text
                raise RuntimeError("Risposta vuota da Gemini API")
            except Exception as e:
                errors.append(f"Gemini Principale ({gemini_config.model}): {e}")
                err_str = str(e).lower()
                is_rate_limit = any(x in err_str for x in ["429", "resource_exhausted", "quota", "rate limit", "too many requests", "vuota", "empty"])
                if is_rate_limit:
                    print(f"Rilevato limite di frequenza/quota (429) per {gemini_config.model}. Circuit Breaker attivato immediatamente.")
                    save_rate_limited_model(gemini_config.model)
                else:
                    err_msg = str(e)
                    print(f"Gemini API ({gemini_config.model}) fallita o congestionata ({err_msg[:80]}...). Tento fallback su altri modelli...")
                        
        # 1b. Tentativo con modelli Gemini di fallback in cascata (gemini-2.5-flash, gemini-3.1-flash-lite, gemini-2.0-flash)
        fallback_models = ["gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.0-flash"]
        for fallback_model in fallback_models:
            # Ricarichiamo le limitazioni per rilevare modifiche in tempo reale fatte da altri thread/processi
            rate_limited_models = load_rate_limited_models()
            if fallback_model in rate_limited_models:
                print(f"Bypass fallback: {fallback_model} è contrassegnato in quota-limit nel file .rate_limits.json.")
                errors.append(f"Gemini Fallback ({fallback_model}): Saltato (in quota-limit).")
                continue
            try:
                print(f"Tentativo di elaborazione con Gemini di Fallback ({fallback_model}) via API REST nativa...")
                resp_text = await call_native_gemini_api(
                    model=fallback_model,
                    api_key=gemini_key,
                    system_instructions=gemini_config.system_instructions,
                    prompt=prompt
                )
                if resp_text and resp_text.strip() != "":
                    return resp_text
                raise RuntimeError(f"Risposta vuota da Gemini API ({fallback_model})")
            except Exception as e2:
                errors.append(f"Gemini Fallback ({fallback_model}): {e2}")
                err_str2 = str(e2).lower()
                is_rate_limit2 = any(x in err_str2 for x in ["429", "resource_exhausted", "quota", "rate limit", "too many requests", "vuota", "empty"])
                if is_rate_limit2:
                    print(f"Rilevato limite di frequenza/quota (429) per fallback {fallback_model}. Circuit Breaker attivato immediatamente.")
                    save_rate_limited_model(fallback_model)
                else:
                    print(f"Gemini fallback ({fallback_model}) fallito: {e2}.")
    else:
        errors.append("Gemini saltato: chiave non valida o dummy-key in GEMINI_API_KEY e Vertex disabilitato.")

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
                prompt=prompt
            )
        except Exception as e:
            errors.append(f"Ollama ({ollama_model}): {e}")
 
    error_summary = " | ".join(errors)
    raise RuntimeError(f"Tutti i provider di fallback sono falliti o non configurati. Dettagli: {error_summary}")


async def transcribe_audio_via_gemini(audio_base64: str, mime_type: str = "audio/ogg") -> str:
    """
    Invia un file audio codificato in base64 a Gemini per la trascrizione.
    Tenta prima con gemini-2.5-flash e i modelli in cascata.
    """
    import os
    import json
    import urllib.request
    import urllib.error
    
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key or gemini_key == "dummy-key" or gemini_key.startswith("YOUR_"):
        raise ValueError("GEMINI_API_KEY non impostata o non valida. Impossibile trascrivere il vocale.")

    # Modelli multimodali da tentare in cascata
    models = ["gemini-2.5-flash", "gemini-3.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    
    errors = []
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
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
            print(f"[Telegram Audio] Tentativo di trascrizione audio con {model}...")
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
            errors.append(f"{model}: {e}")
            print(f"[Telegram Audio] Errore trascrizione con {model}: {e}")
            
    raise RuntimeError(f"Tutti i modelli per la trascrizione sono falliti: {', '.join(errors)}")

