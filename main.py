import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# 1. DUMMY HTTP SERVER UNTUK HEALTH CHECK BACK4APP
# ---------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"OK - Van Hermes Bot is running")

def run_dummy_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"Dummy HTTP Server berjalan di port {port}")
    server.serve_forever()

# ---------------------------------------------------------
# 2. SETUP GEMINI CLIENT & KEAMANAN
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
ALLOWED_USERS = os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def is_authorized(user_id: int) -> bool:
    """Mengecek apakah user berhak mengakses bot"""
    if not ALLOWED_USERS or ALLOWED_USERS == ['']:
        return True
    return str(user_id) in [u.strip() for u in ALLOWED_USERS]

# ---------------------------------------------------------
# 3. HANDLERS TELEGRAM
# ---------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("Maaf, Anda tidak memiliki akses ke agen ini.")
        return
        
    welcome_text = (
        "Halo! Saya **Van Hermes AI Agent**.\n\n"
        "Fitur yang tersedia:\n"
        "1. **Chat Biasa:** Kirim pesan teks langsung untuk bertanya ke Gemini.\n"
        "2. **Affiliate Video Workflow:** Kirim foto produk lalu sertakan caption `/genvideo` atau `genVideo`."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Merespon chat teks biasa dari pengguna"""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("Akses ditolak.")
        return

    if not client:
        await update.message.reply_text("GEMINI_API_KEY belum dikonfigurasi di Back4App.")
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
        logger.error(f"Error saat memproses pesan teks: {e}")
        await update.message.reply_text(f"Terjadi kesalahan saat memproses permintaan Anda: {str(e)}")

async def generate_video_workflow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Workflow analisis foto produk -> Hook Copywriting & Prompt Video 3-5 detik"""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("Akses ditolak.")
        return

    message = update.message

    if not client:
        await message.reply_text("⚠️ API Key Google AI Studio (`GEMINI_API_KEY`) belum dipasang di Back4App.")
        return

    if not message.photo:
        await message.reply_text("Silakan kirim foto produk bersama kata kunci /genvideo atau 'genVideo'.")
        return

    status_msg = await message.reply_text("⏳ **[1/2]** Mengunduh & Menganalisis foto produk...")

    try:
        # 1. Download foto produk dari Telegram
        photo_file = await message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text="💡 **[2/2]** Merancang Hook Copywriting & Prompt Video (3-5 detik)..."
        )

        user_caption = message.caption or ""

        analysis_prompt = f"""
        Kamu adalah seorang Video Director & Expert Affiliate Marketer.
        
        Instruksi Tambahan Pengguna: "{user_caption}"
        
        Tugasmu:
        1. Analisis foto produk ini.
        2. Buat 1 Hook Copywriting yang sangat memikat untuk caption TikTok/Reels (3-5 detik pertama, bahasa Indonesia).
        3. Buat 1 Detailed Video Generation Prompt (dalam bahasa Inggris, durasi 3-5 detik) yang fokus pada visual gerak kamera, lighting, dan showcase produk untuk dimasukkan ke AI Video Generator (seperti Google Veo / Imagen).

        Format Respon (Wajib persis seperti ini):
        📌 **HOOK COPYWRITING:**
        [Isi hook bahasa Indonesia]

        🎬 **PROMPT VIDEO GENERATOR (EN):**
        [Isi prompt bahasa Inggris]
        """

        # 2. Buat Part Gambar yang valid untuk google-genai SDK
        image_part = types.Part.from_bytes(
            data=bytes(photo_bytes),
            mime_type='image/jpeg'
        )

        # 3. Kirim ke Gemini 2.5 Flash
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[image_part, analysis_prompt]
        )

        result_text = response.text if response.text else "Gagal menghasilkan respon dari foto."

        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text=f"✨ **Konsep Affiliate Ready!** ✨\n\n{result_text}\n\n*Catatan: Kamu bisa langsung copy prompt video di atas ke Google AI Studio (Veo) untuk me-render videonya.*",
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Error pada workflow genvideo: {e}")
        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text=f"❌ Terjadi kesalahan saat memproses gambar:\n`{str(e)}`",
            parse_mode="Markdown"
        )

# ---------------------------------------------------------
# 4. UTAMA
# ---------------------------------------------------------
def main():
    if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
        logger.error("Token Telegram dan GEMINI_API_KEY harus diatur di Environment Variables!")
        return

    # 1. Jalankan Dummy Web Server di thread latar belakang untuk Back4App Health Check
    threading.Thread(target=run_dummy_server, daemon=True).start()

    # 2. Inisialisasi Bot Telegram
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 3. Registrasi Handlers
    app.add_handler(CommandHandler("start", start_command))
    
    # Handler Command /genvideo (jika panggil via command saja)
    app.add_handler(CommandHandler("genvideo", generate_video_workflow))
    
    # Handler foto dengan caption berisi 'genvideo' / '/genvideo'
    app.add_handler(
        MessageHandler(
            filters.PHOTO & (filters.CAPTION & filters.Regex(r'(?i)genvideo')),
            generate_video_workflow
        )
    )
    
    # Handler foto tanpa caption genvideo (opsional: diproses sebagai analisis gambar biasa)
    app.add_handler(
        MessageHandler(
            filters.PHOTO & ~filters.CAPTION,
            generate_video_workflow
        )
    )

    # Handler pesan teks biasa
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot Van Hermes berhasil berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
