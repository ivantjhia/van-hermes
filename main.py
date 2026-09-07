import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------
# 1. DUMMY HTTP SERVER FOR BACK4APP HEALTH CHECK
# ---------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"OK - Van Hermes is running!")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server_address = ("", port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"Health check server running on port {port}")
    httpd.serve_forever()

# ---------------------------------------------------------
# 2. SETUP GOOGLE AI STUDIO (GEMINI CLIENT)
# ---------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)

# ---------------------------------------------------------
# 3. TELEGRAM BOT HANDLERS
# ---------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pesan sambutan saat /start"""
    welcome_text = (
        "Halo! Saya **Van Hermes AI Agent**.\n\n"
        "Untuk membuat konsep video promosi affiliate:\n"
        "1. Kirim foto produk.\n"
        "2. Tambahkan caption `/genvideo` atau `genVideo` saat mengirim foto."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def generate_video_workflow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Workflow pembuatan prompt video + hook copywriting"""
    message = update.message

    if not client:
        await message.reply_text("⚠️ API Key Google AI Studio (`GEMINI_API_KEY`) belum dipasang di Environment Variables Back4App.")
        return

    if not message.photo:
        await message.reply_text("Silakan kirim foto produk bersama kata kunci /genvideo atau 'genVideo'.")
        return

    status_msg = await message.reply_text("⏳ **[1/3]** Memproses foto & menganalisis produk...")

    try:
        # Download foto dari Telegram ke memori
        photo_file = await message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text="💡 **[2/3]** Menggenerasi Hook Copywriting & Prompt Video 3-5 detik via Gemini..."
        )

        analysis_prompt = """
        Kamu adalah seorang Video Director & Expert Affiliate Marketer.
        
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

        # Panggil Gemini via SDK google-genai
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                types.Part.from_bytes(
                    data=bytes(photo_bytes),
                    mime_type='image/jpeg',
                ),
                analysis_prompt
            ]
        )

        result_text = response.text

        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text=f"✨ **Konsep Affiliate Ready!** ✨\n\n{result_text}\n\n*Catatan: Kamu bisa langsung copy prompt video di atas ke Google AI Studio (Veo) untuk me-render videonya.*",
            parse_mode="Markdown"
        )

    except Exception as e:
        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text=f"❌ Terjadi kesalahan saat memproses: {str(e)}"
        )

# ---------------------------------------------------------
# 4. MAIN EXECUTION
# ---------------------------------------------------------
def main():
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_TOKEN environment variable is missing!")
        return

    threading.Thread(target=run_health_check_server, daemon=True).start()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("genvideo", generate_video_workflow))
    app.add_handler(
        MessageHandler(
            filters.PHOTO & filters.Regex(r'(?i)genvideo'),
            generate_video_workflow
        )
    )

    print("Bot Van Hermes berhasil berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
