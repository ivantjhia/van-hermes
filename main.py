import os
import logging
import threading
import base64
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
import dashscope

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
# 2. SETUP CLIENTS
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
ALLOWED_USERS = os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

if DASHSCOPE_API_KEY:
    dashscope.api_key = DASHSCOPE_API_KEY

QWEN_BASE_URL = "https://ws-3pp3842ksq2nry2w.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=QWEN_BASE_URL
) if DASHSCOPE_API_KEY else None

def is_authorized(user_id: int) -> bool:
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

    status_msg = await message.reply_text("⏳ **[1/3]** Mengunduh & Memproses foto produk...")

    try:
        # 1. Simpan foto sementara di direktori lokal /tmp kontainer
        photo_file = await message.photo[-1].get_file()
        temp_img_path = "/tmp/product_input.jpg"
        await photo_file.download_to_drive(temp_img_path)

        # Konversi ke base64 untuk analisis Qwen-VL
        with open(temp_img_path, "rb") as f:
            photo_bytes = f.read()
            base64_str = base64.b64encode(photo_bytes).decode('utf-8')
            data_uri = f"data:image/jpeg;base64,{base64_str}"

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
                                "url": data_uri
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
            text="🎬 **[3/3]** Me-render video `.mp4` via Wan2.6..."
        )

        # 3. Panggil DashScope SDK bawaan untuk upload file lokal dan panggil Wan2.6
        # SDK Dashscope akan mengurus otentikasi OSS Alibaba secara otomatis
        task_res = dashscope.Image2Video.async_call(
            model="wan2.6-i2v-flash",
            image_url=f"file://{temp_img_path}",
            prompt=video_prompt
        )

        if task_res.status_code != 200:
            raise Exception(f"Gagal memicu render Wan2.6: {task_res.message}")

        # Polling status tugas sampai selesai
        video_url = None
        import time
        for _ in range(36):
            time.sleep(10)
            status = dashscope.Image2Video.wait(task_res)
            if status.output.task_status == 'SUCCEEDED':
                video_url = status.output.video_url
                break
            elif status.output.task_status in ['FAILED', 'CANCELED']:
                raise Exception(f"Render gagal di Wan2.6: {status.output.message}")

        # 4. Kirim file video ke Telegram
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
            raise Exception("Waktu render habis (Timeout).")

        # Hapus file temporary
        if os.path.exists(temp_img_path):
            os.remove(temp_img_path)

    except Exception as e:
        logger.error(f"Error pada workflow genvideo: {e}")
        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text=f"❌ Terjadi kesalahan saat memproses video:\n`{str(e)}`",
            parse_mode="Markdown"
        )

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

    logger.info("Bot Van Hermes (Dashscope SDK File) berhasil berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
