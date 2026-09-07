import os
import logging
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
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
# 2. SETUP CLIENTS & KEAMANAN
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
ALLOWED_USERS = os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

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
        "Halo! Saya **Van Hermes AI Agent** (Powered by Qwen/Alibaba Cloud).\n\n"
        "Fitur yang tersedia:\n"
        "1. **Chat Biasa:** Kirim pesan teks langsung untuk bertanya ke Qwen LLM.\n"
        "2. **Affiliate Video Workflow:** Kirim foto produk lalu sertakan caption `/genvideo` atau `genVideo`."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Merespon chat teks biasa menggunakan Qwen LLM"""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("Akses ditolak.")
        return

    if not DASHSCOPE_API_KEY:
        await update.message.reply_text("DASHSCOPE_API_KEY belum dikonfigurasi di Back4App.")
        return

    user_text = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        response = dashscope.Generation.call(
            model='qwen-max',
            messages=[
                {'role': 'system', 'content': 'Kamu adalah asisten AI Van Hermes yang cerdas dan ramah.'},
                {'role': 'user', 'content': user_text}
            ]
        )
        if response.status_code == 200:
            reply_text = response.output.text
            await update.message.reply_text(reply_text)
        else:
            await update.message.reply_text(f"Error Qwen: {response.message}")

    except Exception as e:
        logger.error(f"Error saat memproses pesan teks: {e}")
        await update.message.reply_text(f"Terjadi kesalahan saat memproses permintaan Anda: {str(e)}")

async def generate_video_workflow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Workflow analisis foto via Qwen VL -> Render Video via Qwen WanX -> Kirim .mp4"""
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

    status_msg = await message.reply_text("⏳ **[1/3]** Mengunduh & Menganalisis foto produk via Qwen-VL...")

    try:
        # 1. Download foto produk dari Telegram
        photo_file = await message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

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

        # Panggil Qwen-VL untuk membaca gambar produk
        vl_response = dashscope.MultiModalConversation.call(
            model='qwen-vl-plus',
            messages=[
                {
                    'role': 'user',
                    'content': [
                        {'image': f'file://{temp_img_path}'},
                        {'text': analysis_prompt}
                    ]
                }
            ]
        )

        if vl_response.status_code != 200:
            raise Exception(f"Gagal memproses gambar via Qwen-VL: {vl_response.message}")

        result_text = vl_response.output.choices[0].message.content[0]['text']

        # Ekstrak prompt video untuk WanX
        video_prompt = "A high quality product showcase video, smooth camera zoom in"
        if "🎬 **PROMPT VIDEO GENERATOR:**" in result_text:
            video_prompt = result_text.split("🎬 **PROMPT VIDEO GENERATOR:**")[-1].strip()

        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text="🎬 **[2/3]** Mengirim prompt & foto ke Qwen WanX untuk me-render video..."
        )

        # 2. Panggil API WanX Image-to-Video
        rsp = dashscope.Image2Video.async_call(
            model='wanx-v1',
            image_url=f"file://{temp_img_path}",
            prompt=video_prompt
        )

        if rsp.status_code != 200:
            raise Exception(f"Gagal memanggil Qwen WanX API: {rsp.message}")

        await context.bot.edit_message_text(
            chat_id=message.chat_id,
            message_id=status_msg.message_id,
            text="⏳ **[3/3]** Me-render video di Qwen Cloud (butuh waktu ~1-2 menit)..."
        )

        # 3. Polling sampai video selesai
        video_url = None
        for _ in range(36):  # Cek berkala max 6 menit
            time.sleep(10)
            task_status = dashscope.Image2Video.wait(rsp)
            if task_status.output.task_status == 'SUCCEEDED':
                video_url = task_status.output.video_url
                break
            elif task_status.output.task_status in ['FAILED', 'CANCELED']:
                raise Exception(f"Render video gagal di Qwen Studio: {task_status.output.message}")

        # 4. Kirimkan video hasil render ke Telegram
        if video_url:
            caption_reply = f"🎥 **Video Promosi Ready (via Qwen AI)!**\n\n{result_text}"
            await context.bot.send_video(
                chat_id=message.chat_id,
                video=video_url,
                caption=caption_reply,
                parse_mode="Markdown"
            )
            await context.bot.delete_message(chat_id=message.chat_id, message_id=status_msg.message_id)
        else:
            await context.bot.edit_message_text(
                chat_id=message.chat_id,
                message_id=status_msg.message_id,
                text="⚠️ Waktu render video habis (timeout)."
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

    logger.info("Bot Van Hermes (Full Qwen) berhasil berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
