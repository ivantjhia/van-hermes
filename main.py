import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Ambil Environment Variables dari Koyeb
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Inisialisasi Google GenAI Client
client = genai.Client(api_key=GEMINI_API_KEY)

# Fungsi Validasi Pengguna Telegram
def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USERS or ALLOWED_USERS == ['']:
        return True
    return str(user_id) in [u.strip() for u in ALLOWED_USERS]

# Handler Perintah /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("Maaf, Anda tidak memiliki akses ke agen ini.")
        return
    await update.message.reply_text("Halo! Hermes Agent siap membantu Anda. Silakan kirim pesan atau instruksi.")

# Handler Pesan Teks (Proses AI)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("Akses ditolak.")
        return

    user_text = update.message.text
    
    # Kirim indikator "typing..." di Telegram
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        # Panggil Model Gemini Flash
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
        logger.error("TELEGRAM_BOT_TOKEN dan GEMINI_API_KEY harus diatur di Environment Variables!")
        return

    # Inisialisasi Bot Telegram
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register Handler
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Jalankan Bot (Long Polling)
    logger.info("Hermes Agent sedang berjalan di Koyeb...")
    app.run_polling()

if __name__ == "__main__":
    main()
