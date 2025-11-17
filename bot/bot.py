import os
import asyncio
import libtorrent as lt
import time
import subprocess
import re
import zipfile
import mimetypes
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from urllib.parse import urlparse

# Get the bot token from the environment variable
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables")

# Max file size for Telegram (2GB)
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB in bytes

# --- Kawaii Progress Bar con acento maracucho ---
def create_kawaii_progress_bar(percentage, length=10):
    """Create a cute progress bar with kaomojis and maracucho accent"""
    filled = int(length * percentage / 100)
    empty = length - filled

    # Mensajes maracuchos
    if percentage < 25:
        kaomoji = "(｡•́︿•̀｡)"
        status = "Arrancando esta vaina... "
    elif percentage < 50:
        kaomoji = "(｡◕‿◕｡)"
        status = "Ahí vamos verga... "
    elif percentage < 75:
        kaomoji = "(๑˃ᴗ˂)ﻭ"
        status = "Casi listo coño! "
    elif percentage < 100:
        kaomoji = "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧"
        status = "Ya merito maldito! "
    else:
        kaomoji = "(ﾉ´ヮ`)ﾉ*: ･ﾟ"
        status = "Listo papa! "

    # Create bar with cute symbols
    bar = "█" * filled + "░" * empty

    return f"{kaomoji} {status}\n[{bar}] {percentage:.1f}%"

# --- Mediafire Download Logic ---
async def download_mediafire(url, save_path, chat_id, context, message_id):
    """Downloads a file from MediaFire with kawaii progress."""
    try:
        # Get the page
        response = requests.get(url)
        response.raise_for_status()

        # Parse the HTML to find the download link
        soup = BeautifulSoup(response.text, 'html.parser')

        # MediaFire has the download link in a specific element
        download_link = soup.find('a', {'id': 'downloadButton'})
        if not download_link:
            # Try alternative method
            download_link = soup.find('a', {'aria-label': 'Download file'})

        if not download_link:
            raise ValueError("Could not find download link on MediaFire page")

        download_url = download_link.get('href')

        # Download the file
        file_response = requests.get(download_url, stream=True)
        file_response.raise_for_status()

        # Get filename and total size
        filename = None
        if 'Content-Disposition' in file_response.headers:
            content_disp = file_response.headers['Content-Disposition']
            filename_match = re.findall('filename="(.+)"', content_disp)
            if filename_match:
                filename = filename_match[0]

        if not filename:
            filename = os.path.basename(urlparse(download_url).path)

        total_size = int(file_response.headers.get('content-length', 0))
        filepath = os.path.join(save_path, filename)

        # Write the file with progress updates
        downloaded = 0
        last_update = 0
        with open(filepath, 'wb') as f:
            for chunk in file_response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)

                # Update progress every 5%
                if total_size > 0:
                    progress = (downloaded / total_size) * 100
                    if progress - last_update >= 5:
                        last_update = progress
                        progress_bar = create_kawaii_progress_bar(progress)
                        status_text = (
                            f"✨ Bajando de MediaFire marico\n\n"
                            f"{progress_bar}\n\n"
                            f"📦 Archivo: {filename}\n"
                            f"💾 Descargado: {downloaded / (1024**2):.1f}MB / {total_size / (1024**2):.1f}MB"
                        )
                        try:
                            await context.bot.edit_message_text(text=status_text, chat_id=chat_id, message_id=message_id)
                        except:
                            pass  # Ignore if message hasn't changed

        return filepath
    except Exception as e:
        raise Exception(f"MediaFire download failed: {str(e)}")

# --- File Handling Functions ---
def is_video_file(filepath):
    """Check if a file is a video."""
    mime_type, _ = mimetypes.guess_type(filepath)
    return mime_type and mime_type.startswith('video/')

def get_video_duration(filepath):
    """Get video duration using ffprobe."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', filepath],
            capture_output=True,
            text=True
        )
        return float(result.stdout.strip())
    except:
        return 0

def split_video_ffmpeg(filepath, max_size=MAX_FILE_SIZE):
    """Split video file using ffmpeg into parts under max_size."""
    parts = []
    file_size = os.path.getsize(filepath)

    if file_size <= max_size:
        return [filepath]

    # Get video duration
    duration = get_video_duration(filepath)
    if duration == 0:
        raise ValueError("Could not determine video duration")

    # Calculate number of parts needed
    num_parts = (file_size // max_size) + 1
    part_duration = duration / num_parts

    base_name = os.path.splitext(filepath)[0]
    ext = os.path.splitext(filepath)[1]

    for i in range(int(num_parts)):
        start_time = i * part_duration
        output_file = f"{base_name}_part{i+1}{ext}"

        # Use ffmpeg to split
        subprocess.run([
            'ffmpeg', '-i', filepath, '-ss', str(start_time),
            '-t', str(part_duration), '-c', 'copy', output_file, '-y'
        ], check=True, capture_output=True)

        parts.append(output_file)

    return parts

def split_file_zip(filepath, max_size=MAX_FILE_SIZE):
    """Split non-video file into zip parts."""
    parts = []
    file_size = os.path.getsize(filepath)

    if file_size <= max_size:
        return [filepath]

    # Calculate number of parts
    num_parts = (file_size // max_size) + 1
    chunk_size = file_size // num_parts

    base_name = os.path.basename(filepath)

    with open(filepath, 'rb') as f:
        for i in range(int(num_parts)):
            part_name = f"{base_name}.part{i+1}.zip"
            part_path = os.path.join(os.path.dirname(filepath), part_name)

            # Read chunk
            chunk = f.read(chunk_size if i < num_parts - 1 else -1)

            # Create zip file
            with zipfile.ZipFile(part_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{base_name}.part{i+1}", chunk)

            parts.append(part_path)

    return parts

# --- Torrent Download Logic ---
async def download_torrent_and_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, magnet_link: str):
    """Downloads a torrent from a magnet link and uploads the largest file to Telegram."""
    chat_id = update.effective_chat.id
    ses = lt.session()
    ses.listen_on(6881, 6891)
    params = lt.parse_magnet_uri(magnet_link)
    params.save_path = '/downloads'
    handle = ses.add_torrent(params)

    message = await context.bot.send_message(chat_id, "Arrancando esta vaina vale...")

    while not handle.has_metadata():
        await asyncio.sleep(1)

    torinfo = handle.get_torrent_info()
    largest_file = max(torinfo.files(), key=lambda f: f.size)
    file_path = os.path.join(params.save_path, largest_file.path)

    while not handle.status().is_seeding:
        s = handle.status()
        state_str = ['queued', 'checking', 'downloading metadata', 'downloading', 'finished', 'seeding', 'allocating']
        progress = s.progress * 100

        # Create kawaii progress bar
        progress_bar = create_kawaii_progress_bar(progress)

        status_text = (
            f"✨ Bajando este peo: {torinfo.name()}\n\n"
            f"{progress_bar}\n\n"
            f"💫 Estado: {state_str[s.state]}\n"
            f"⬇️ Bajando: {s.download_rate / 1000:.1f} kB/s\n"
            f"⬆️ Subiendo: {s.upload_rate / 1000:.1f} kB/s\n"
            f"👥 Peers: {s.num_peers}"
        )

        await context.bot.edit_message_text(text=status_text, chat_id=chat_id, message_id=message.message_id)
        await asyncio.sleep(5)

    await context.bot.edit_message_text(text="(ﾉ´ヮ`)ﾉ*: ･ﾟ ¡Ya bajó esa mierda! Procesando...", chat_id=chat_id, message_id=message.message_id)

    try:
        # Check file size and split if needed
        file_size = os.path.getsize(file_path)
        files_to_upload = []

        if file_size > MAX_FILE_SIZE:
            await context.bot.edit_message_text(
                text=f"(ಠ_ಠ) ¡Coño! El archivo pesa {file_size / (1024**3):.2f}GB\n✂️ Voy a partirlo en pedazos marico...",
                chat_id=chat_id,
                message_id=message.message_id
            )

            if is_video_file(file_path):
                files_to_upload = split_video_ffmpeg(file_path)
            else:
                files_to_upload = split_file_zip(file_path)
        else:
            files_to_upload = [file_path]

        await context.bot.edit_message_text(text="(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧ ¡Subiendo esa vaina ahora!", chat_id=chat_id, message_id=message.message_id)

        # Upload files
        for idx, file_to_upload in enumerate(files_to_upload):
            part_info = f" (Part {idx+1}/{len(files_to_upload)})" if len(files_to_upload) > 1 else ""

            if is_video_file(file_to_upload):
                # Upload as video (compressed)
                await context.bot.send_video(
                    chat_id,
                    video=open(file_to_upload, 'rb'),
                    supports_streaming=True,
                    caption=f"{os.path.basename(file_to_upload)}{part_info}",
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=120
                )
            else:
                # Upload as document
                await context.bot.send_document(
                    chat_id,
                    document=open(file_to_upload, 'rb'),
                    caption=f"{os.path.basename(file_to_upload)}{part_info}",
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=120
                )

        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)

    except Exception as e:
        await context.bot.send_message(chat_id, f"Failed to upload file: {e}")
    finally:
        # Clean up all files
        if file_size > MAX_FILE_SIZE:
            for f in files_to_upload:
                if os.path.exists(f):
                    os.remove(f)

        if os.path.exists(file_path):
            os.remove(file_path)
        ses.remove_torrent(handle)


# --- MediaFire Download and Upload ---
async def download_mediafire_and_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Downloads a file from MediaFire and uploads it to Telegram."""
    chat_id = update.effective_chat.id
    message = await context.bot.send_message(chat_id, "(｡◕‿◕｡) Arrancando con MediaFire vale...")

    try:
        # Download from MediaFire
        filepath = await download_mediafire(url, '/downloads', chat_id, context, message.message_id)
        file_size = os.path.getsize(filepath)

        await context.bot.edit_message_text(
            text=f"(ﾉ´ヮ`)ﾉ*: ･ﾟ ¡Ya bajó esa vaina!\nTamaño: {file_size / (1024**2):.2f}MB\nProcesando este peo...",
            chat_id=chat_id,
            message_id=message.message_id
        )

        # Handle splitting if needed
        files_to_upload = []

        if file_size > MAX_FILE_SIZE:
            await context.bot.edit_message_text(
                text=f"(ಠ_ಠ) ¡Maldito! Esta mierda pesa {file_size / (1024**3):.2f}GB\n✂️ Lo voy a partir en pedazos verga...",
                chat_id=chat_id,
                message_id=message.message_id
            )

            if is_video_file(filepath):
                files_to_upload = split_video_ffmpeg(filepath)
            else:
                files_to_upload = split_file_zip(filepath)
        else:
            files_to_upload = [filepath]

        await context.bot.edit_message_text(text="(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧ ¡A subir ese coño!", chat_id=chat_id, message_id=message.message_id)

        # Upload files
        for idx, file_to_upload in enumerate(files_to_upload):
            part_info = f" (Part {idx+1}/{len(files_to_upload)})" if len(files_to_upload) > 1 else ""

            if is_video_file(file_to_upload):
                # Upload as video (compressed)
                await context.bot.send_video(
                    chat_id,
                    video=open(file_to_upload, 'rb'),
                    supports_streaming=True,
                    caption=f"{os.path.basename(file_to_upload)}{part_info}",
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=120
                )
            else:
                # Upload as document
                await context.bot.send_document(
                    chat_id,
                    document=open(file_to_upload, 'rb'),
                    caption=f"{os.path.basename(file_to_upload)}{part_info}",
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=120
                )

        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)

    except Exception as e:
        await context.bot.send_message(chat_id, f"Failed to download/upload from MediaFire: {e}")
    finally:
        # Clean up all files
        if file_size > MAX_FILE_SIZE:
            for f in files_to_upload:
                if os.path.exists(f):
                    os.remove(f)

        if os.path.exists(filepath):
            os.remove(filepath)


# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text(
        "¡Épale marico! Bot de descargas a la orden ✨\n\n"
        "Mándame:\n"
        "- Un enlace magnet para bajar torrents\n"
        "- Un enlace de MediaFire para bajar archivos\n\n"
        "Los videos los subo como media comprimida papa.\n"
        "Si pesa más de 2GB, lo parto en pedazos verga.\n\n"
        "Dale pues, manda ese enlace que yo te lo bajo (｡◕‿◕｡)"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming messages and starts the appropriate download."""
    text = update.message.text

    # Solo responder si es un enlace válido (no hacer flood)
    if text.startswith("magnet:?"):
        await download_torrent_and_upload(update, context, text)
    elif "mediafire.com" in text:
        await download_mediafire_and_upload(update, context, text)
    # Si no es un enlace válido, ignorar el mensaje (no responder nada)

def main():
    """Starts the bot."""
    application = Application.builder() \
        .token(BOT_TOKEN) \
        .base_url('http://telegram-bot-api:8081/bot') \
        .base_file_url('http://telegram-bot-api:8081/file/bot') \
        .http_version('1.1') \
        .get_updates_http_version('1.1') \
        .build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Run the bot until the user presses Ctrl-C
    application.run_polling()

if __name__ == '__main__':
    main()
