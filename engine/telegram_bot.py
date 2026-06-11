import os
import sys
from dotenv import load_dotenv

# Carica le variabili d'ambiente dal percorso assoluto del progetto
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(project_root, ".env"))

# Aggiungi la cartella radice al path per gli import
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

from engine.query_agent import query_agent_answer
from engine.tools.vault_tools import get_vault_path
from engine.utils.chat_memory import ChatMemory
import httpx

DASHBOARD_URL = "http://localhost:8000"

# Initialize memory
vault_path = get_vault_path()
chat_memory = ChatMemory(os.path.join(vault_path, "telegram_memory.json"), max_messages=14) # 7 turns


def is_authorized(update: Update) -> bool:
    allowed_users_str = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    if not allowed_users_str:
        return True
    user = update.effective_user
    if not user:
        return False
    allowed_ids = [x.strip() for x in allowed_users_str.split(",") if x.strip()]
    return str(user.id) in allowed_ids

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Non sei autorizzato ad utilizzare questo bot.")
        return
    await update.message.reply_text(
        "Ciao! Sono il bot del tuo Secondo Cervello. Puoi usarmi nei seguenti modi:\n\n"
        "💬 *Scrivimi una domanda* in linguaggio naturale per consultare la tua base di conoscenza.\n"
        "📊 /status - Verifica lo stato dell'ingestore e quanti file ci sono in coda.\n"
        "📥 /ingest [sorgente] - Avvia manualmente il processo di sincronizzazione e ingestione. Puoi facoltativamente specificare la sorgente (es. notion, drive, mail, calendar, web, tutto).\n"
        "⏹️ /stop [sorgente] - Ferma il processo di ingestione in corso.",
        parse_mode="Markdown"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Non sei autorizzato ad utilizzare questo bot.")
        return
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{DASHBOARD_URL}/api/status", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                running_str = "Attivo 🟢" if data["running"] else "Fermo 🔴"
                active_source = f" (Sorgente: {data['active_source']})" if data["running"] else ""
                await update.message.reply_text(
                    f"📊 *Stato Secondo Cervello*\n\n"
                    f"• Ingestore: {running_str}{active_source}\n"
                    f"• File in coda: {data['queue_count']}\n"
                    f"• Orario pianificato: {data['schedule_time']}",
                    parse_mode="Markdown"
                )
                return
    except Exception:
        pass
    
    # Fallback se la dashboard è offline
    from engine.tools.vault_tools import list_unprocessed_raw
    unprocessed = list_unprocessed_raw()
    await update.message.reply_text(
        f"📊 *Stato Secondo Cervello* (Dashboard offline)\n\n"
        f"• File in coda: {len(unprocessed)}",
        parse_mode="Markdown"
    )

async def ingest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Non sei autorizzato ad utilizzare questo bot.")
        return
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Gestione dell'argomento se presente
    if context.args:
        source_raw = context.args[0].lower()
        mapping = {
            "notion": "notion",
            "drive": "drive",
            "google-drive": "drive",
            "mail": "mail",
            "email": "mail",
            "calendar": "calendar",
            "calendario": "calendar",
            "web": "web",
            "clip": "web",
            "tutto": "all",
            "all": "all"
        }
        if source_raw not in mapping:
            await update.message.reply_text(
                f"⚠️ Sorgente sconosciuta: '{source_raw}'.\n"
                f"Scegli tra: notion, drive, mail, calendar, web, tutto."
            )
            return
            
        source = mapping[source_raw]
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{DASHBOARD_URL}/api/ingest/start?source={source}", timeout=5.0)
                if resp.status_code == 200:
                    await update.message.reply_text(f"📥 Ingestione per *{source}* avviata con successo in background!", parse_mode="Markdown")
                    return
                elif resp.status_code == 400:
                    await update.message.reply_text(f"⚠️ L'ingestione è già in corso (Sorgente: {resp.json().get('active_source')}).")
                    return
        except Exception as e:
            await update.message.reply_text(f"❌ Impossibile avviare: dashboard non raggiungibile ({e})")
            return
            
    # Se non c'è argomento, mostra la tastiera inline
    keyboard = [
        [
            InlineKeyboardButton("📓 Notion", callback_data="ingest:notion"),
            InlineKeyboardButton("📁 Google Drive", callback_data="ingest:drive")
        ],
        [
            InlineKeyboardButton("✉️ Email", callback_data="ingest:mail"),
            InlineKeyboardButton("🗓️ Calendario", callback_data="ingest:calendar")
        ],
        [
            InlineKeyboardButton("🌐 Web Clip", callback_data="ingest:web"),
            InlineKeyboardButton("📥 Tutto", callback_data="ingest:all")
        ],
        [
            InlineKeyboardButton("❌ Annulla", callback_data="ingest:cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📥 *Scegli la sorgente da ingerire*:", reply_markup=reply_markup, parse_mode="Markdown")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Non sei autorizzato ad utilizzare questo bot.")
        return
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Controlla lo stato della dashboard per vedere se c'è un processo attivo
    active_source = None
    running = False
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{DASHBOARD_URL}/api/status", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                running = data["running"]
                active_source = data["active_source"]
    except Exception:
        pass
        
    if not running:
        await update.message.reply_text("⚠️ Nessun processo di Ingestione attivo al momento.")
        return
        
    # Gestione dell'argomento se presente
    if context.args:
        target_raw = context.args[0].lower()
        mapping = {
            "notion": "notion",
            "drive": "drive",
            "google-drive": "drive",
            "mail": "mail",
            "email": "mail",
            "calendar": "calendar",
            "calendario": "calendar",
            "web": "web",
            "clip": "web",
            "tutto": "all",
            "all": "all"
        }
        target = mapping.get(target_raw, target_raw)
        
        if target == active_source or target in ["all", "all"]:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(f"{DASHBOARD_URL}/api/ingest/stop", timeout=5.0)
                    if resp.status_code == 200:
                        await update.message.reply_text(f"⏹️ Ingestione attiva ({active_source}) interrotta con successo.")
                        return
            except Exception as e:
                await update.message.reply_text(f"❌ Impossibile fermare: dashboard non raggiungibile ({e})")
                return
        else:
            # La sorgente non corrisponde a quella attiva
            keyboard = [
                [
                    InlineKeyboardButton("⏹️ Sì, ferma comunque", callback_data="stop:confirm"),
                    InlineKeyboardButton("❌ No, annulla", callback_data="stop:cancel")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"⚠️ L'ingestione attiva è per *{active_source}*, non per *{target_raw}*.\n"
                f"Vuoi fermarla comunque?",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return
            
    # Se non c'è argomento, chiedi conferma tramite Inline Keyboard
    keyboard = [
        [
            InlineKeyboardButton("⏹️ Sì, ferma", callback_data="stop:confirm"),
            InlineKeyboardButton("❌ No, annulla", callback_data="stop:cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"⏹️ *Conferma arresto*\n\nSei sicuro di voler fermare l'ingestione attiva per *{active_source}*?",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(update):
        await query.answer(text="Non sei autorizzato ad utilizzare questo bot.", show_alert=True)
        return
    await query.answer()
    
    data = query.data
    
    if data.startswith("ingest:"):
        source = data.split(":")[1]
        if source == "cancel":
            await query.edit_message_text("❌ Operazione annullata.")
            return
            
        await query.edit_message_text(f"⏳ Avvio dell'ingestione per: *{source}*...", parse_mode="Markdown")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{DASHBOARD_URL}/api/ingest/start?source={source}", timeout=5.0)
                if resp.status_code == 200:
                    await query.edit_message_text(f"📥 Ingestione per *{source}* avviata con successo in background!", parse_mode="Markdown")
                elif resp.status_code == 400:
                    await query.edit_message_text(f"⚠️ L'ingestione è già in corso ({resp.json().get('active_source')}).")
        except Exception as e:
            await query.edit_message_text(f"❌ Impossibile avviare: dashboard non raggiungibile ({e})")
            
    elif data.startswith("stop:"):
        action = data.split(":")[1]
        if action == "cancel":
            await query.edit_message_text("❌ Operazione annullata. L'ingestione continua.")
            return
            
        await query.edit_message_text("⏳ Arresto dell'ingestione in corso...")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{DASHBOARD_URL}/api/ingest/stop", timeout=5.0)
                if resp.status_code == 200:
                    await query.edit_message_text("⏹️ Ingestione interrotta con successo.")
                elif resp.status_code == 400:
                    await query.edit_message_text("⚠️ Nessun processo di ingestione attivo da fermare.")
        except Exception as e:
            await query.edit_message_text(f"❌ Impossibile fermare: dashboard non raggiungibile ({e})")

def format_for_telegram(text: str) -> str:
    import re
    # 1. Gestisci wikilink con pipe: [[Percorso/Nota|Testo da mostrare]] -> Testo da mostrare
    text = re.sub(r'\[\[[^\]|]+\|([^\]]+)\]\]', r'\1', text)
    # 2. Gestisci wikilink semplici: [[Nome Nota]] -> Nome Nota
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    # 3. Converti grassetti standard ** in * (Telegram legacy Markdown usa * per il grassetto)
    text = text.replace("**", "*")
    return text

def split_message(text: str, chunk_size: int = 4000) -> list[str]:
    chunks = []
    while len(text) > chunk_size:
        # Trova l'ultimo newline entro il chunk_size
        split_at = text.rfind('\n', 0, chunk_size)
        if split_at == -1:
            # Fallback allo spazio
            split_at = text.rfind(' ', 0, chunk_size)
            if split_at == -1:
                # Forza lo split a metà parola
                split_at = chunk_size
        chunks.append(text[:split_at])
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    return chunks

async def process_text_query(user_message: str, chat_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Aggiungi il messaggio dell'utente alla memoria
        chat_memory.add_message(chat_id, "user", user_message)
        history = chat_memory.get_history(chat_id)
        
        conversation_id = chat_memory.get_conversation_id(chat_id)
        # Passa la history e il conversation_id all'agente
        answer = await query_agent_answer(user_message, history=history, conversation_id=conversation_id)
        
        # Aggiungi la risposta alla memoria
        chat_memory.add_message(chat_id, "model", answer)
        
        formatted_answer = format_for_telegram(answer)
        
        # Splitting del messaggio se troppo lungo
        chunks = split_message(formatted_answer)
        for chunk in chunks:
            try:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            except Exception as telegram_err:
                print(f"[Telegram] Invio con parse_mode='Markdown' fallito ({telegram_err}). Invio come testo semplice...")
                await update.message.reply_text(chunk)
                
    except Exception as e:
        await update.message.reply_text(f"Errore durante l'elaborazione della domanda: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Non sei autorizzato ad utilizzare questo bot.")
        return
    user_message = update.message.text
    chat_id = update.effective_chat.id
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Comandi speciali di reset contesto (opzionale ma utile)
    if user_message.lower().strip() == "/clear":
        chat_memory.clear_history(chat_id)
        await update.message.reply_text("Memoria della conversazione azzerata.")
        return
        
    await process_text_query(user_message, chat_id, update, context)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Non sei autorizzato ad utilizzare questo bot.")
        return
    chat_id = update.effective_chat.id
    
    # Mostra l'indicazione che sta registrando/scrivendo
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        voice = update.message.voice
        if not voice:
            await update.message.reply_text("Errore: nessun messaggio vocale rilevato.")
            return
            
        voice_file = await context.bot.get_file(voice.file_id)
        
        import io
        import base64
        from engine.utils.llm_fallback import transcribe_audio_via_gemini
        
        out = io.BytesIO()
        await voice_file.download_to_memory(out)
        audio_bytes = out.getvalue()
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        
        # Inviamo un messaggio temporaneo per dare feedback che la trascrizione è iniziata
        status_msg = await update.message.reply_text("🎤 _Trascrizione del vocale in corso..._", parse_mode="Markdown")
        
        try:
            transcription = await transcribe_audio_via_gemini(audio_base64, mime_type="audio/ogg")
        except Exception as trans_err:
            await status_msg.edit_text(f"❌ Errore durante la trascrizione del vocale: {trans_err}")
            return
            
        # Aggiorna il messaggio temporaneo con la trascrizione
        await status_msg.edit_text(f"🎤 *Trascrizione vocale:*\n_{transcription}_", parse_mode="Markdown")
        
        # Processa la query testuale
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        await process_text_query(transcription, chat_id, update, context)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Errore durante l'elaborazione del vocale: {e}")


def main():
    if not TELEGRAM_AVAILABLE:
        print("Errore: Libreria 'python-telegram-bot' non installata.")
        sys.exit(1)
        
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token.startswith("YOUR_"):
        print("Errore: TELEGRAM_BOT_TOKEN non impostato nel file .env.")
        sys.exit(1)
        
    print("Avvio del bot Telegram...")
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("ingest", ingest_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))

    application.run_polling()

if __name__ == "__main__":
    main()
