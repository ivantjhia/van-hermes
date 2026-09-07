import os
import logging
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI

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
# 2. SETUP OPENAI-COMPATIBLE CLIENT (ALIBABA MAAS)
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
ALLOWED_USERS = os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

QWEN_BASE_URL = "https://ws-3pp3842ksq2nry2w.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=QWEN_BASE_URL
) if DASHSCOPE_API_KEY else None

def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USERS or ALLOWED_USERS == ['']:
        return True
    return str(user_id) in [u.strip() for u in ALLOWED_USERS]

def upload_image_to_litterbox(photo_bytes: bytes) -> str:
    """Mengunggah foto ke Litterbox (Catbox Temporary) untuk mendapatkan Direct Public HTTPS URL"""
    url = "https://litterbox.catbox.moe/resources/internals/api.php"
    files = {
        'fileToUpload': ('image.jpg', photo_bytes, 'image/jpeg')
    }
    data = {
        'reqtype': 'fileupload',
        'time': '1h'
    }
    res = requests.post(url, data=data, files=files, timeout=30)
    if res.status_code == 200 and res.text.strip().startswith("https://"):
        return res.text.strip()
    else:
        raise Exception(f"Gagal mengunggah foto ke Public Host: {res.text}")

# ---------------------------------------------------------
# 3. HANDLERS TELEGRAM
# ---------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("Maaf, Anda tidak memiliki akses ke agen ini.")
        return
        
    welcome_text = (
        "Halo! Saya **Van Hermes AI Agent** (Powered by Wan2.6-I2V-flash).\n\n"
        "Fitur yang tersedia:\n"
        "1. **Chat Biasa:** Kirim pesan teks langsung untuk bertanya ke Qwen LLM (`qwen-flash`).\n"
        "2. **Affiliate Video Workflow:** Kirim foto produk lalu sertakan caption `/genvideo` atau `genVideo`."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("Akses ditolak.")
        return

    if not client:
        await update.message.reply_text("DASHSCOPE_API_KEY belum dikonfigurasi di Back4App.")
        return

    user_text = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        response = client.chat.completions.create(
            model="qwen-flash",
            messages=[
                {"role": "system", "content": "Kamu adalah asisten AI Van Hermes yang cerdas, helpful, dan ramah."},
                {"role": "user", "content": user_text}
            ]
        )
        reply_text = response.choices[0].message.content
        await update.message.reply_text(reply_text)

    except Exception as e:
        logger.error(f"Error saat memproses pesan teks: {e}")
        await update.message.reply_text(f"Terjadi kesalahan saat memproses permintaan Anda: {str(e)}")

async def generate_video_workflow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Workflow analisis foto via Qwen-VL -> Upload Public Host -> Render Wan2.6 -> Kirim .mp4"""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("Akses ditolak.")
        return

    message = update.message

    if not DASHSCOPE_API_KEY:
        await message.reply_text("⚠️ API Key Qwen/DashScope (`DASHSCOPE_API_KEY`) belum dipasang di Back4App.")
        return

    if not message.photo:
        await message.reply_text("Silakan kirim foto produk bersama kata kunci /genvideo.")
        return

    status_msg = await message.reply_text("⏳ **[1/3]** Mengunduh & Mengunggah foto ke Public Host...")

    try:
        # 1. Download foto dari Telegram & Upload ke Litterbox
        photo_file = await message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        public_image_url = upload_image_to_litterbox(photo_bytes)

        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text="💡 **[2/3]** Menganalisis foto produk via Qwen-VL..."
        )

        user_caption = message.caption or ""

        analysis_prompt = f"""
        Kamu adalah seorang Video Director & Expert Affiliate Marketer.
        
        Instruksi Tambahan Pengguna dari Caption:
        "{user_caption}"
        
        Tugasmu:
        1. Analisis foto produk ini.
        2. Buat 1 Hook Copywriting yang sangat memikat untuk caption TikTok/Reels (3-5 detik pertama, bahasa Indonesia).
        3. Buat 1 Short Detailed Video Generation Prompt (dalam bahasa Inggris, maksimal 40 kata) yang fokus pada visual gerak kamera cinematic dan keindahan produk.

        Format Respon (Wajib persis seperti ini):
        📌 **HOOK COPYWRITING:**
        [Isi hook bahasa Indonesia]

        🎬 **PROMPT VIDEO GENERATOR (EN):**
        [Isi prompt bahasa Inggris]
        """

        # 2. Analisis via Qwen-VL
        response = client.chat.completions.create(
            model="qwen-vl-max",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": analysis_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": public_image_url
                            }
                        }
                    ]
                }
            ]
        )

        result_text = response.choices[0].message.content

        video_prompt = "A high quality cinematic product showcase video, smooth camera zoom in"
        if "🎬 **PROMPT VIDEO GENERATOR (EN):**" in result_text:
            video_prompt = result_text.split("🎬 **PROMPT VIDEO GENERATOR (EN):**")[-1].strip()

        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text="🎬 **[3/3]** Me-render video `.mp4` via Wan2.6-I2V-flash..."
        )

        # 3. Trigger Render Video Synchronous dengan Public Image URL
        task_url = "https://ws-3pp3842ksq2nry2w.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/image2video/video-synthesis"
        headers = {
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "wan2.6-i2v-flash",
            "input": {
                "image_url": public_image_url,
                "prompt": video_prompt
            }
        }

        task_res = requests.post(task_url, headers=headers, json=payload, timeout=120)
        task_json = task_res.json()

        video_url = None
        if task_res.status_code == 200 and "output" in task_json:
            video_url = task_json["output"].get("video_url")

        # 4. Kirimkan File Video .mp4 Hasil Render ke Telegram
        if video_url:
            caption_reply = f"🎥 **Video Promosi Ready (Wan2.6-I2V-flash)!**\n\n{result_text}"
            await context.bot.send_video(
                chat_id=message.chat_id,
                video=video_url,
                caption=caption_reply,
                parse_mode="Markdown"
            )
            await context.bot.delete_message(chat_id=message.chat_id, message_id=status_msg.message_id)
        else:
            error_msg = task_json.get("message", task_res.text)
            raise Exception(f"Gagal memicu render Wan2.6-I2V-flash: {error_msg}")

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
    if not TELEGRAM_BOT_TOKEN or not DASHSCOPE_API_KEY:
        logger.error("Token Telegram dan DASHSCOPE_API_KEY harus diatur di Environment Variables!")
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

    logger.info("Bot Van Hermes (Litterbox Fix) berhasil berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
