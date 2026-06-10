import os
import sys
import re
import asyncio
import subprocess
from typing import Optional, List
from fastapi import FastAPI, Request, Response, Header, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# Carica le variabili d'ambiente prima di tutto
load_dotenv()

# Add root folder to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.tools.vault_tools import get_vault_path, list_unprocessed_raw, search_wiki
from engine.utils.markdown import parse_markdown
from engine.query_agent import query_agent_answer
from engine.watcher import watch_vault_changes
from engine.tools.mail_idle import start_imap_idle_listeners

# FastMCP Server Import
try:
    from mcp.server.fastmcp import FastMCP
    mcp_server = FastMCP("Second Brain")
except ImportError:
    mcp_server = None

import datetime
try:
    from croniter import croniter
except ImportError:
    croniter = None

# --- Unified Background Scheduler ---
class ScheduledTask:
    def __init__(self, name: str, command_args: List[str], timing_key: str):
        self.name = name
        self.command_args = command_args
        self.timing_key = timing_key
        self.last_run: Optional[datetime.datetime] = None
        self.next_run: Optional[datetime.datetime] = None
        self.interval_seconds: Optional[int] = None
        self.last_expr: Optional[str] = None
        
    def update_schedule(self, timing_dict: dict, now: datetime.datetime, force_update: bool = False):
        val = timing_dict.get(self.timing_key)
        if not val:
            self.next_run = None
            self.interval_seconds = None
            self.last_expr = None
            return
            
        val_str = str(val).strip()
        if val_str == self.last_expr and not force_update and self.next_run is not None:
            return
            
        self.last_expr = val_str
        
        if val_str.isdigit():
            self.interval_seconds = int(val_str)
            if self.last_run is None:
                self.next_run = now + datetime.timedelta(seconds=self.interval_seconds)
            else:
                self.next_run = self.last_run + datetime.timedelta(seconds=self.interval_seconds)
        else:
            if croniter is None:
                print(f"[SCHEDULER] Errore: libreria 'croniter' non disponibile. Impossibile pianificare {self.name}.", flush=True)
                self.next_run = None
                return
            try:
                cron = croniter(val_str, now)
                self.next_run = cron.get_next(datetime.datetime)
                self.interval_seconds = None
            except Exception as e:
                print(f"[SCHEDULER] Errore parsing cron '{val_str}' per {self.name}: {e}", flush=True)
                self.next_run = None
                
    def should_run(self, now: datetime.datetime) -> bool:
        if not self.next_run:
            return False
        return now >= self.next_run

scheduler_tasks = [
    ScheduledTask("Sincronizzazione ed ingestione", ["ingest"], "sync_and_ingest"),
    ScheduledTask("Riflessione settimanale", ["reflect"], "weekly_reflection"),
    ScheduledTask("Briefing pre-evento", ["briefing"], "briefing"),
    ScheduledTask("Dream mode notturna", ["dream"], "dream")
]

async def run_task_subprocess(task: ScheduledTask):
    vault_path = get_vault_path()
    python_exe = os.path.join(vault_path, ".venv", "bin", "python")
    if not os.path.exists(python_exe):
        python_exe = sys.executable
        
    args = [python_exe, "-u", "-m", "engine.main"] + task.command_args
    print(f"[SCHEDULER] Avvio compito: {task.name} ({' '.join(args)})...", flush=True)
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=vault_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        
        # Consuma output
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="ignore").strip()
            print(f"[{task.name}] {line}", flush=True)
            
        await proc.wait()
        print(f"[SCHEDULER] Compito completato: {task.name} con codice {proc.returncode}", flush=True)
    except Exception as e:
        print(f"[SCHEDULER] Errore nell'esecuzione del compito {task.name}: {e}", flush=True)

async def run_scheduler_loop():
    print("[SCHEDULER] Avvio del ciclo dello scheduler universale...", flush=True)
    await asyncio.sleep(5)
    vault_path = get_vault_path()
    
    while True:
        try:
            now = datetime.datetime.now()
            settings_path = os.path.join(vault_path, "settings.md")
            timing_dict = {}
            if os.path.exists(settings_path):
                try:
                    with open(settings_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    fm, _ = parse_markdown(content)
                    timing_dict = fm.get("timing", {})
                except Exception as e:
                    print(f"[SCHEDULER] Errore di lettura settings.md: {e}", flush=True)
                    
            for task in scheduler_tasks:
                task.update_schedule(timing_dict, now)
                if task.should_run(now):
                    task.last_run = now
                    task.update_schedule(timing_dict, now, force_update=True)
                    asyncio.create_task(run_task_subprocess(task))
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[SCHEDULER] Errore imprevisto nel loop: {e}", flush=True)
            
        await asyncio.sleep(10)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Avvia lo scheduler in background
    scheduler_task = asyncio.create_task(run_scheduler_loop())
    
    # Avvia il file watcher per modifiche locali
    watcher_task = asyncio.create_task(watch_vault_changes(manager))
    
    # Avvia i listener IMAP IDLE per le email
    idle_tasks = []
    try:
        idle_tasks = await start_imap_idle_listeners(manager)
    except Exception as e:
        print(f"[DASHBOARD] Errore nell'avvio dei listener IMAP IDLE: {e}", flush=True)
        
    yield
    
    # Cancellazione e pulizia all'arresto
    scheduler_task.cancel()
    watcher_task.cancel()
    for task in idle_tasks:
        task.cancel()
        
    # Attesa terminazione
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass
    for task in idle_tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass

app = FastAPI(title="Secondo Cervello - Dashboard", lifespan=lifespan)

from fastapi.staticfiles import StaticFiles
app.mount("/fonts", StaticFiles(directory=os.path.join(get_vault_path(), "fonts")), name="fonts")

class TimeScheduleRequest(BaseModel):
    time: str  # Format: "HH:MM"

# --- Ingestion Process Manager ---
class IngestionManager:
    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.lock = asyncio.Lock()
        self.log_history: List[str] = []
        self.listeners: List[asyncio.Queue] = []
        self.max_history = 1000
        self.active_source: str = "none"

    async def start(self, source: Optional[str] = None) -> bool:
        async with self.lock:
            if self.is_running():
                return False
            
            vault_path = get_vault_path()
            python_exe = os.path.join(vault_path, ".venv", "bin", "python")
            if not os.path.exists(python_exe):
                python_exe = sys.executable  # Fallback
                
            self.log_history.clear()
            self.active_source = source or "all"
            
            args = [python_exe, "-u", "-m", "engine.main", "ingest"]
            if source and source != "all":
                args.extend(["--source", source])
                
            self.process = await asyncio.create_subprocess_exec(
                *args,
                cwd=vault_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                preexec_fn=os.setsid if os.name != 'nt' else None
            )
            
            # Start background reader task
            asyncio.create_task(self._read_output())
            return True

    async def _read_output(self):
        # Read lines asynchronously
        while self.process and self.process.stdout:
            line_bytes = await self.process.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="ignore").strip()
            
            # Print to stdout too so it shows in server console
            print(f"[INGESTION] {line}", flush=True)
            
            # Add to history
            self.log_history.append(line)
            if len(self.log_history) > self.max_history:
                self.log_history.pop(0)
                
            # Broadcast to listeners
            for q in list(self.listeners):
                await q.put(line)
                
        # Clean up process reference when complete
        async with self.lock:
            self.process = None
            self.active_source = "none"

    async def stop(self) -> bool:
        async with self.lock:
            if not self.is_running():
                return False
            try:
                import signal
                if os.name != 'nt':
                    # Send SIGTERM to the process group
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                else:
                    self.process.terminate()
                    
                # Wait up to 5 seconds
                for _ in range(50):
                    if self.process is None:
                        break
                    await asyncio.sleep(0.1)
                    
                # Force kill if still running
                if self.process is not None:
                    if os.name != 'nt':
                        os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    else:
                        self.process.kill()
            except Exception as e:
                print(f"Errore nell'interrompere l'ingestione: {e}")
            finally:
                self.process = None
                self.active_source = "none"
            return True

    def is_running(self) -> bool:
        return self.process is not None

    def register_listener(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.listeners.append(q)
        return q

    def unregister_listener(self, q: asyncio.Queue):
        if q in self.listeners:
            self.listeners.remove(q)

manager = IngestionManager()

# --- Helper Functions for Settings ---
def get_schedule_time() -> str:
    vault_path = get_vault_path()
    settings_path = os.path.join(vault_path, "settings.md")
    if not os.path.exists(settings_path):
        return "10:00"
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            content = f.read()
        fm, _ = parse_markdown(content)
        cron_str = fm.get("timing", {}).get("sync_and_ingest", "0 10 * * *")
        match = re.match(r'^(\d+)\s+(\d+)', cron_str.strip())
        if match:
            minute, hour = match.groups()
            return f"{int(hour):02d}:{int(minute):02d}"
    except Exception as e:
        print(f"Errore lettura orario schedulato: {e}")
    return "10:00"

def set_schedule_time(time_str: str) -> bool:
    try:
        hour, minute = time_str.split(":")
        cron_str = f"{int(minute)} {int(hour)} * * *"
        
        vault_path = get_vault_path()
        settings_path = os.path.join(vault_path, "settings.md")
        with open(settings_path, "r", encoding="utf-8") as f:
            content = f.read()
        fm, body = parse_markdown(content)
        if "timing" not in fm:
            fm["timing"] = {}
        fm["timing"]["sync_and_ingest"] = cron_str
        
        from engine.utils.markdown import to_markdown
        new_content = to_markdown(fm, body)
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        # Rigenera launchd plist
        python_exe = os.path.join(vault_path, ".venv", "bin", "python")
        subprocess.run([python_exe, "-m", "engine.plist_generator", "install"], cwd=vault_path)
        return True
    except Exception as e:
        print(f"Errore nel salvare l'orario: {e}")
        return False

# --- Graph Engine Backend ---
_graph_cache = None
_graph_cache_time = 0

def build_graph_data():
    global _graph_cache, _graph_cache_time
    import time
    if _graph_cache and (time.time() - _graph_cache_time < 3600):
        return _graph_cache
        
    vault_path = get_vault_path()
    nodes = []
    links = []
    wiki_re = re.compile(r'\[\[(.*?)\]\]')
    folders = ["wiki", "CRM", "Meetings", "People", "journal", "Microthemes"]
    node_set = set()
    edges = []
    
    for folder in folders:
        abs_folder = os.path.join(vault_path, folder)
        if not os.path.exists(abs_folder): continue
        for root, _, files in os.walk(abs_folder):
            for file in files:
                if file.endswith(".md"):
                    file_path = os.path.join(root, file)
                    node_id = file.replace(".md", "")
                    node_set.add(node_id)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            matches = wiki_re.findall(content)
                            for match in matches:
                                target = match.split("|")[0].strip()
                                edges.append({"source": node_id, "target": target})
                                node_set.add(target)
                    except:
                        pass
                        
    for n in node_set:
        degree = sum(1 for e in edges if e["source"] == n or e["target"] == n)
        nodes.append({"id": n, "name": n, "val": max(degree, 1), "group": 1})
        
    for e in edges:
        links.append({"source": e["source"], "target": e["target"]})
        
    _graph_cache = {"nodes": nodes, "links": links}
    _graph_cache_time = time.time()
    return _graph_cache

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None

# --- Web UI Routes ---
@app.get("/graph", response_class=HTMLResponse)
def read_graph():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "graph_chat.html")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()
    return "Template non trovato."

@app.get("/api/graph")
def get_graph():
    return build_graph_data()

@app.get("/api/wiki")
def get_wiki_page(path: str):
    """
    Ritorna il contenuto di una pagina wiki specificata dal percorso relativo o dal titolo,
    effettuando una ricerca tollerante all'interno delle cartelle del vault.
    """
    vault_path = get_vault_path()
    clean_path = os.path.normpath(path).replace("\\", "/").lstrip('/')
    if clean_path.startswith("..") or os.path.isabs(clean_path):
        raise HTTPException(status_code=400, detail="Percorso non valido.")
        
    # Se il file non esiste direttamente con estensione .md, proviamo a risolverlo
    if not clean_path.endswith(".md"):
        # 1. Controlla cartelle comuni
        possible_folders = ["wiki/entities", "wiki/concepts", "wiki/sources", "wiki/synthesis", "CRM", "Meetings", "journal", "Microthemes"]
        found = False
        for folder in possible_folders:
            test_path = os.path.join(folder, clean_path + ".md")
            if os.path.exists(os.path.join(vault_path, test_path)):
                clean_path = test_path
                found = True
                break
                
        # 2. Se non ancora trovato, cammina nel vault per cercare NoteName.md
        if not found:
            filename = os.path.basename(clean_path)
            if not filename.endswith(".md"):
                filename += ".md"
            for root, _, files in os.walk(vault_path):
                # Salta cartelle di configurazione/ambiente
                if any(x in root for x in [".git", ".venv", ".pytest_cache", "__pycache__"]):
                    continue
                if filename in files:
                    clean_path = os.path.relpath(os.path.join(root, filename), vault_path)
                    found = True
                    break
                    
    # Assicurati di aggiungere .md se manca ed è un file locale diretto
    if not clean_path.endswith(".md"):
        clean_path += ".md"
        
    abs_path = os.path.join(vault_path, clean_path)
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail=f"Pagina wiki '{path}' non trovata.")
        
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        fm, body = parse_markdown(content)
        title = os.path.splitext(os.path.basename(clean_path))[0]
        return {
            "path": clean_path,
            "title": title,
            "frontmatter": fm,
            "content": body
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    try:
        ans = await query_agent_answer(req.message, history=req.history)
        wiki_re = re.compile(r'\[\[(.*?)\]\]')
        cited = [m.split("|")[0].strip() for m in wiki_re.findall(ans)]
        return {"answer": ans, "cited_nodes": cited}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/", response_class=HTMLResponse)
def read_root():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()
    return """
    <html>
        <head><title>Dashboard Errore</title></head>
        <body style="background:#0d0f12;color:#fff;font-family:sans-serif;padding:50px;text-align:center;">
            <h1>Dashboard Template non trovato!</h1>
            <p>Verifica che <code>engine/templates/index.html</code> esista.</p>
        </body>
    </html>
    """

@app.get("/api/status")
def get_status():
    unprocessed = list_unprocessed_raw()
    
    # Extract tail of log.md
    log_tail = []
    vault_path = get_vault_path()
    log_path = os.path.join(vault_path, "log.md")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                log_tail = [l.strip() for l in lines[-15:] if l.strip()]
        except Exception:
            pass
            
    return {
        "running": manager.is_running(),
        "active_source": manager.active_source,
        "queue_count": len(unprocessed),
        "queue_preview": unprocessed[:10],
        "log_history": manager.log_history,
        "log_tail": log_tail,
        "schedule_time": get_schedule_time()
    }

@app.post("/api/ingest/start")
async def start_ingest(source: Optional[str] = None):
    started = await manager.start(source=source)
    if started:
        return {"status": "started", "source": source or "all"}
    return JSONResponse(status_code=400, content={"status": "already_running", "active_source": manager.active_source})

@app.post("/api/ingest/stop")
async def stop_ingest():
    stopped = await manager.stop()
    if stopped:
        return {"status": "stopped"}
    return JSONResponse(status_code=400, content={"status": "not_running"})

@app.post("/api/schedule")
def update_schedule(req: TimeScheduleRequest):
    success = set_schedule_time(req.time)
    if success:
        return {"status": "updated", "time": req.time}
    return JSONResponse(status_code=500, content={"status": "error_updating"})

@app.get("/api/logs/stream")
async def logs_stream(request: Request):
    q = manager.register_listener()
    
    async def event_generator():
        try:
            # Send current history first
            for line in manager.log_history:
                yield f"data: {line}\n\n"
                
            # Stream new lines
            while True:
                if request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {line}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat
                    yield "data: :heartbeat\n\n"
        finally:
            manager.unregister_listener(q)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/webhook/{source}")
async def trigger_webhook(source: str, x_webhook_secret: Optional[str] = Header(None)):
    secret = os.getenv("WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="WEBHOOK_SECRET non configurato nel file .env.")
    if x_webhook_secret != secret:
        raise HTTPException(status_code=401, detail="Secret non valido o mancante.")
    
    valid_sources = ["notion", "drive", "mail", "web", "calendar", "all"]
    if source not in valid_sources:
        raise HTTPException(status_code=400, detail=f"Sorgente non valida. Deve essere una tra: {valid_sources}")
        
    started = await manager.start(source=source)
    if started:
        return {"status": "triggered", "source": source}
    return JSONResponse(status_code=400, content={"status": "already_running", "active_source": manager.active_source})

# --- MCP Server Integration ---
if mcp_server is not None:
    @mcp_server.tool()
    async def query_second_brain(question: str) -> str:
        """Interroga il secondo cervello con una domanda in linguaggio naturale e ottieni una risposta basata sui dati del vault."""
        try:
            ans = await query_agent_answer(question)
            return ans
        except Exception as e:
            return f"Errore durante l'interrogazione: {e}"

    @mcp_server.tool()
    def search_vault(query: str) -> str:
        """Cerca riferimenti e note nel vault Obsidian contenenti le parole chiave."""
        try:
            results = search_wiki(query)
            if not results:
                return "Nessun risultato trovato nel vault."
            out = []
            for r in results:
                out.append(f"- **[[{r['path'].replace('.md', '')}]]** ({r['title']}):\n  {r['snippet']}")
            return "\n\n".join(out)
        except Exception as e:
            return f"Errore durante la ricerca: {e}"

    @mcp_server.tool()
    async def trigger_ingestion_sync() -> str:
        """Avvia il processo di sincronizzazione ed ingestion delle fonti nel Secondo Cervello in background."""
        started = await manager.start()
        if started:
            return "Ingestione avviata con successo in background."
        return "L'ingestione è già in esecuzione."
        
    @mcp_server.tool()
    def get_queue_status() -> str:
        """Ottiene il numero di file in coda ed elenca i primi 10 file non ancora elaborati."""
        unprocessed = list_unprocessed_raw()
        status_running = "in esecuzione" if manager.is_running() else "fermo"
        out = [f"Stato Ingestione: {status_running}"]
        out.append(f"File in coda: {len(unprocessed)}")
        if unprocessed:
            out.append("\nPrimi file in coda:")
            for u in unprocessed[:10]:
                out.append(f"- {u}")
        return "\n".join(out)

    # Mount the MCP server's SSE application to FastAPI app at /mcp
    app.mount("/mcp", mcp_server.sse_app())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
