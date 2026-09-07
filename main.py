# 1. Ambil URL Publik Gambar langsung dari Server Telegram
photo_file = await message.photo[-1].get_file()
telegram_image_url = photo_file.file_path  
# URL ini berbentuk: https://api.telegram.org/file/bot<TOKEN>/photos/file_xxx.jpg

# 2. Kirim Direct URL tersebut ke Wan2.6
payload = {
    "model": "wan2.6-i2v-flash",
    "input": {
        "image_url": telegram_image_url,
        "prompt": video_prompt
    }
}
