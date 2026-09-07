import os
import logging
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types
import dashscope
from dashscope.aigc.image2video import Image2Video

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
# 2. SETUP CLIENTS & KEAMANAN
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
ALLOWED_USERS = os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

if DASHSCOPE_API_KEY:
    dashscope.api_key = DASHSCOPE_API_KEY

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
        "2. **Affiliate Video Workflow (Qwen WanX):** Kirim foto produk lalu sertakan caption `/genvideo` atau `genVideo`."
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
    """Workflow analisis foto via Gemini -> Render Video via Qwen WanX (DashScope) -> Kirim .mp4"""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("Akses ditolak.")
        return

    message = update.message

    if not client:
        await message.reply_text("⚠️ API Key Google AI Studio (`GEMINI_API_KEY`) belum dipasang di Back4App.")
        return

    if not DASHSCOPE_API_KEY:
        await message.reply_text("⚠️ API Key Qwen/DashScope (`DASHSCOPE_API_KEY`) belum dipasang di Back4App.")
        return

    if not message.photo:
        await message.reply_text("Silakan kirim foto produk bersama kata kunci /genvideo.")
        return

    status_msg = await message.reply_text("⏳ **[1/3]** Mengunduh foto & merancang konsep via Gemini...")

    try:
        # 1. Download foto produk dari Telegram
        photo_file = await message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        # Simpan file sementara untuk diunggah ke Qwen WanX API
        temp_img_path = "/tmp/product_input.jpg"
        with open(temp_img_path, "wb") as f:
            f.write(photo_bytes)

        user_caption = message.caption or ""

        analysis_prompt = f"""
        Kamu adalah seorang Video Director & Expert Affiliate Marketer.
        
        Instruksi/Arah Tambahan Pengguna dari Caption:
        "{user_caption}"
        
        Tugasmu:
        1. Analisis foto produk ini beserta instruksi tambahan pengguna.
        2. Buat 1 Hook Copywriting yang sangat memikat untuk caption TikTok/Reels (3-5 detik pertama, bahasa Indonesia).
        3. Buat 1 Detailed Video Generation Prompt (dalam bahasa Inggris, maksimal 50 kata) yang fokus pada visual gerak kamera, lighting, dan showcase produk.

        Format Respon (Wajib persis seperti ini):
        📌 **HOOK COPYWRITING:**
        [Isi hook bahasa Indonesia]

        🎬 **PROMPT VIDEO GENERATOR:**
        [Isi prompt bahasa Inggris saja]
        """

        image_part = types.Part.from_bytes(
            data=bytes(photo_bytes),
            mime_type='image/jpeg'
        )

        # Minta Gemini buat Hook & Video Prompt
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[image_part, analysis_prompt]
        )

        result_text = response.text if response.text else ""

        # Ekstrak prompt video (teks di bawah 🎬 PROMPT VIDEO GENERATOR:)
        video_prompt = "A high quality cinematic product showcase video, smooth camera zoom in"
        if "🎬 **PROMPT VIDEO GENERATOR:**" in result_text:
            video_prompt = result_text.split("🎬 **PROMPT VIDEO GENERATOR:**")[-1].strip()

        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text="🎬 **[2/3]** Mengirim prompt & foto ke Qwen WanX (DashScope API)..."
        )

        # 2. Panggil API WanX Image-to-Video dari DashScope
        rsp = Image2Video.async_call(
            model='wanx-v1',
            image_url=f"file://{temp_img_path}",
            prompt=video_prompt
        )

        if rsp.status_code != 200:
            raise Exception(f"Gagal memanggil Qwen API: {rsp.message}")

        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text="⏳ **[3/3]** Me-render video di Qwen Cloud (butuh waktu ~1-2 menit)..."
        )

        # 3. Looping Polling sampai video selesai di-render
        video_url = None
        for _ in range(36):  # Cek berkala max 6 menit
            time.sleep(10)
            task_status = Image2Video.wait(rsp)
            if task_status.output.task_status == 'SUCCEEDED':
                video_url = task_status.output.video_url
                break
            elif task_status.output.task_status in ['FAILED', 'CANCELED']:
                raise Exception(f"Render video gagal di Qwen Studio: {task_status.output.message}")

        # 4. Kirimkan video hasil render ke Telegram
        if video_url:
            caption_reply = f"🎥 **Video Promosi Ready (via Qwen WanX)!**\n\n{result_text}"
            await context.bot.send_video(
                chat_id=message.chat_id,
                video=video_url,
                caption=caption_reply,
                parse_mode="Markdown"
            )
            # Hapus pesan status loading
            await context.bot.delete_message(chat_id=message.chat_id, message_id=status_msg.message_id)
        else:
            await context.bot.edit_message_text(
                chat_id=message.chat_id,
                message_id=status_msg.message_id,
                text="⚠️ Proses render video mengalami timeout."
            )

    except Exception as e:
        logger.error(f"Error pada workflow genvideo: {e}")
        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text=f"❌ Terjadi kesalahan saat memproses video:\n`{str(e)}`",
            parse_mode="Markdown"
        )

# ---------------------------------------------------------
# 4. UTAMA
# ---------------------------------------------------------
def main():
    if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
        logger.error("Token Telegram dan GEMINI_API_KEY harus diatur di Environment Variables!")
        return

    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("genvideo", generate_video_workflow))
    
    app.add_handler(
        MessageHandler(
            filters.PHOTO & filters.CaptionRegex(r'(?i).*genvideo.*'),
            generate_video_workflow
        )
    )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot Van Hermes berhasil berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
