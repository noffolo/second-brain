import os
import json
import ssl
import urllib.request
import urllib.error
import asyncio
from google.antigravity import Agent, LocalAgentConfig

try:
    ssl_context = ssl._create_unverified_context()
except AttributeError:
    ssl_context = None

async def call_openai_compatible_api(url: str, api_key: str, model: str, system_instructions: str, prompt: str) -> str:
    """
    Effettua una chiamata HTTP asincrona (tramite thread pool) a un endpoint compatibile con OpenAI.
    """
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

async def call_llm_with_fallback(prompt: str, system_instructions: str, gemini_config: LocalAgentConfig) -> str:
    """
    Tenta di chiamare il modello Gemini di default (gemini-3.5-flash) tramite l'SDK Google Antigravity.
    Se fallisce, tenta con gemini-3.1-flash.
    Se entrambi i modelli Gemini falliscono o sono congestionati, tenta la chiamata
    in cascata sui provider di fallback disponibili (OpenAI -> DeepSeek -> Together -> DashScope -> Zhipu)
    utilizzando i rispettivi modelli richiesti dall'utente.
    """
    import os
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

    max_retries = 3
    base_delay = 4
    errors = []
    
    # 1a. Tentativo con Gemini Principale (da settings.md, es. gemini-3.5-flash)
    for attempt in range(max_retries + 1):
        try:
            print(f"Tentativo di elaborazione con Gemini ({gemini_config.model}) via Antigravity SDK...")
            async with Agent(gemini_config) as agent:
                response = await agent.chat(prompt)
                resp_text = await response.text()
            if resp_text and resp_text.strip() != "":
                return resp_text
            raise RuntimeError("Risposta vuota da Gemini SDK")
        except Exception as e:
            errors.append(f"Gemini Principale ({gemini_config.model}): {e}")
            err_str = str(e).lower()
            is_rate_limit = any(x in err_str for x in ["429", "resource_exhausted", "quota", "rate limit", "too many requests"])
            if is_rate_limit and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                print(f"Rilevato limite di frequenza (429) per {gemini_config.model}. Attesa di {delay} secondi (tentativo {attempt + 1}/{max_retries})...")
                await asyncio.sleep(delay)
            else:
                err_msg = str(e)
                print(f"Gemini API ({gemini_config.model}) fallita o congestionata ({err_msg[:80]}...). Tento fallback su gemini-1.5-flash...")
                break
                
    # 1b. Tentativo con Gemini Secondario (gemini-1.5-flash)
    for attempt in range(max_retries + 1):
        try:
            fallback_gemini_config = LocalAgentConfig(
                model="gemini-1.5-flash",
                system_instructions=gemini_config.system_instructions
            )
            print(f"Tentativo di elaborazione con Gemini Secondario (gemini-1.5-flash) via Antigravity SDK...")
            async with Agent(fallback_gemini_config) as agent:
                response = await agent.chat(prompt)
                resp_text = await response.text()
            if resp_text and resp_text.strip() != "":
                return resp_text
            raise RuntimeError("Risposta vuota da Gemini SDK (gemini-1.5-flash)")
        except Exception as e2:
            errors.append(f"Gemini Secondario (gemini-1.5-flash): {e2}")
            err_str2 = str(e2).lower()
            is_rate_limit2 = any(x in err_str2 for x in ["429", "resource_exhausted", "quota", "rate limit", "too many requests"])
            if is_rate_limit2 and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                print(f"Rilevato limite di frequenza (429) per gemini-1.5-flash. Attesa di {delay} secondi (tentativo {attempt + 1}/{max_retries})...")
                await asyncio.sleep(delay)
            else:
                print(f"Gemini fallback (gemini-1.5-flash) fallito: {e2}. Avvio cascata di fallback multi-provider...")
                break

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
 
    error_summary = " | ".join(errors)
    raise RuntimeError(f"Tutti i provider di fallback sono falliti o non configurati. Dettagli: {error_summary}")
