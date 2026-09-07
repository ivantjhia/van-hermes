import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Dummy Web Server untuk mengelabui Health Check Back4App
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK - Bot is running")

def run_dummy_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"Dummy HTTP Server berjalan di port {port}")
    server.serve_forever()

# --- Konfigurasi Bot Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USERS or ALLOWED_USERS == ['']:
        return True
    return str(user_id) in [u.strip() for u in ALLOWED_USERS]

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("Maaf, Anda tidak memiliki akses ke agen ini.")
        return
    await update.message.reply_text("Halo! Bot Gemini siap membantu Anda.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("Akses ditolak.")
        return

    user_text = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_text,
        )
        reply_text = response.text if response.text else "Maaf, tidak ada respons yang dihasilkan."
        await update.message.reply_text(reply_text)

    except Exception as e:
        logger.error(f"Error saat memproses pesan: {e}")
        await update.message.reply_text("Terjadi kesalahan saat memproses permintaan Anda.")

def main():
    if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
        logger.error("TELEGRAM_BOT_TOKEN dan GEMINI_API_KEY harus diatur!")
        return

    # Jalankan Dummy HTTP Server di background thread agar Back4App Health Check berhasil
    threading.Thread(target=run_dummy_server, daemon=True).start()

    # Jalankan Bot Telegram
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot sedang berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
