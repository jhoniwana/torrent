import os
import asyncio
import libtorrent as lt
import time
import subprocess
import re
import zipfile
import mimetypes
import requests
import logging
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import TimedOut, NetworkError, RetryAfter, TelegramError
from urllib.parse import urlparse
from functools import wraps

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get the bot token from the environment variable
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables")

# Max file size for Telegram (2GB)
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB in bytes

# Upload settings
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
UPLOAD_TIMEOUT = 1800  # 30 minutes for large files (1.85GB needs time!)


# --- Progress Tracking File Wrapper ---
class ProgressFileWrapper:
    """Wraps a file object to track upload progress."""
    def __init__(self, file_obj, total_size, callback, update_interval=5):
        self.file = file_obj
        self.total_size = total_size
        self.bytes_read = 0
        self.callback = callback
        self.last_update = 0
        self.update_interval = update_interval  # Update every N percent
        self.last_update_time = time.time()

    def read(self, size=-1):
        chunk = self.file.read(size)
        self.bytes_read += len(chunk)

        if self.total_size > 0:
            progress = (self.bytes_read / self.total_size) * 100
            current_time = time.time()

            # Update every N% or every 3 seconds
            if (progress - self.last_update >= self.update_interval or
                current_time - self.last_update_time >= 3):
                self.last_update = progress
                self.last_update_time = current_time
                if self.callback:
                    asyncio.create_task(self.callback(progress, self.bytes_read, self.total_size))

            # Special message when 100% read - Telegram still processing
            if progress >= 100 and self.last_update < 100:
                self.last_update = 100
                if self.callback:
                    asyncio.create_task(self.callback(100, self.bytes_read, self.total_size))

        return chunk

    def seek(self, pos, whence=0):
        result = self.file.seek(pos, whence)
        if whence == 0:
            self.bytes_read = pos
        return result

    def tell(self):
        return self.file.tell()

    def close(self):
        return self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

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


def create_upload_progress_bar(percentage, bytes_sent, total_bytes, length=10):
    """Create a progress bar specifically for uploads."""
    filled = int(length * percentage / 100)
    empty = length - filled

    if percentage < 25:
        kaomoji = "(ノಠ益ಠ)ノ"
        status = "Enviando ese peo... "
    elif percentage < 50:
        kaomoji = "(•̀ᴗ•́)و"
        status = "Ahí va la vaina... "
    elif percentage < 75:
        kaomoji = "(ง'̀-'́)ง"
        status = "¡Dale que casi! "
    elif percentage < 100:
        kaomoji = "ヽ(>∀<☆)☆"
        status = "¡Ya merito coño! "
    else:
        kaomoji = "⏳"
        status = "Telegram procesando... "

    bar = "█" * filled + "░" * empty

    # Format sizes
    sent_mb = bytes_sent / (1024 * 1024)
    total_mb = total_bytes / (1024 * 1024)

    if total_mb >= 1024:
        sent_str = f"{sent_mb / 1024:.2f}GB"
        total_str = f"{total_mb / 1024:.2f}GB"
    else:
        sent_str = f"{sent_mb:.1f}MB"
        total_str = f"{total_mb:.1f}MB"

    return f"{kaomoji} {status}\n[{bar}] {percentage:.1f}%\n📤 {sent_str} / {total_str}"


async def upload_file_with_retry(context, chat_id, file_path, message_id, is_video=False, caption="", part_info=""):
    """Upload a file with progress tracking and retry logic."""
    file_size = os.path.getsize(file_path)
    filename = os.path.basename(file_path)
    size_str = f"{file_size / (1024**3):.2f}GB" if file_size >= 1024**3 else f"{file_size / (1024**2):.1f}MB"
    file_type = "🎬 Video" if is_video else "📄 Documento"
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"Upload attempt {attempt}/{MAX_RETRIES} for {filename}")

        # Show initial status before starting upload
        try:
            await context.bot.edit_message_text(
                text=f"📤 **Iniciando subida**{part_info}\n\n"
                     f"📦 `{filename}`\n"
                     f"💾 Tamaño: {size_str}\n"
                     f"📁 Tipo: {file_type}\n"
                     f"🔄 Intento: {attempt}/{MAX_RETRIES}\n\n"
                     f"(ノಠ益ಠ)ノ Conectando con Telegram...\n"
                     f"[░░░░░░░░░░] 0%",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='Markdown'
            )
        except:
            pass

        try:
            # Create progress callback
            async def update_progress(progress, bytes_sent, total_bytes):
                try:
                    if progress >= 100:
                        # Special message when file fully read - waiting for Telegram
                        status_text = (
                            f"📤 **Enviando a Telegram**{part_info}\n\n"
                            f"⏳ Archivo leído al 100%\n"
                            f"🔄 Telegram está procesando...\n\n"
                            f"⚠️ **Esto puede tardar varios minutos**\n"
                            f"para archivos grandes. ¡No cierres!\n\n"
                            f"📦 `{filename}`\n"
                            f"💾 {size_str}\n"
                            f"🔄 Intento: {attempt}/{MAX_RETRIES}"
                        )
                    else:
                        progress_bar = create_upload_progress_bar(progress, bytes_sent, total_bytes)
                        status_text = (
                            f"📤 **Subiendo archivo**{part_info}\n\n"
                            f"{progress_bar}\n\n"
                            f"📦 `{filename}`\n"
                            f"🔄 Intento: {attempt}/{MAX_RETRIES}"
                        )
                    await context.bot.edit_message_text(
                        text=status_text,
                        chat_id=chat_id,
                        message_id=message_id,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    # Ignore message edit errors (too frequent updates, etc)
                    pass

            # Use local file path for telegram-bot-api (no memory loading!)
            # The local bot API can read files directly from the shared volume
            # Convert /downloads/file to file:///var/lib/telegram-bot-api/file
            local_api_path = file_path.replace('/downloads/', 'file:///var/lib/telegram-bot-api/')

            try:
                await context.bot.edit_message_text(
                    text=f"📤 **Subiendo a Telegram**{part_info}\n\n"
                         f"⏳ Enviando archivo al servidor...\n"
                         f"🔄 Esto puede tardar varios minutos\n\n"
                         f"📦 `{filename}`\n"
                         f"💾 {size_str}\n"
                         f"🔄 Intento: {attempt}/{MAX_RETRIES}\n\n"
                         f"⚠️ **No cierres el chat**",
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='Markdown'
                )
            except:
                pass

            logger.info(f"Uploading via local path: {local_api_path}")

            if is_video:
                await context.bot.send_video(
                    chat_id,
                    video=local_api_path,  # Use file:// URI for local bot API
                    supports_streaming=True,
                    caption=f"{filename}{part_info}",
                    read_timeout=UPLOAD_TIMEOUT,
                    write_timeout=UPLOAD_TIMEOUT,
                    connect_timeout=60
                )
            else:
                await context.bot.send_document(
                    chat_id,
                    document=local_api_path,  # Use file:// URI for local bot API
                    caption=f"{filename}{part_info}",
                    read_timeout=UPLOAD_TIMEOUT,
                    write_timeout=UPLOAD_TIMEOUT,
                    connect_timeout=60
                )

            logger.info(f"Successfully uploaded {filename}")
            return True

        except RetryAfter as e:
            wait_time = e.retry_after
            logger.warning(f"Rate limited. Waiting {wait_time} seconds...")
            await context.bot.edit_message_text(
                text=f"⏳ Telegram dice que espere {wait_time} segundos marico...\n🔄 Reintentando después...",
                chat_id=chat_id,
                message_id=message_id
            )
            await asyncio.sleep(wait_time)
            last_error = f"Rate limited (waited {wait_time}s)"

        except TimedOut as e:
            logger.warning(f"Upload timed out on attempt {attempt}: {e}")
            last_error = f"Timeout - La conexión tardó demasiado"
            if attempt < MAX_RETRIES:
                await context.bot.edit_message_text(
                    text=f"⏰ Timeout en la subida marico...\n🔄 Reintentando ({attempt}/{MAX_RETRIES})...\n⏳ Esperando {RETRY_DELAY}s...",
                    chat_id=chat_id,
                    message_id=message_id
                )
                await asyncio.sleep(RETRY_DELAY * attempt)  # Exponential backoff

        except NetworkError as e:
            logger.warning(f"Network error on attempt {attempt}: {e}")
            last_error = f"Error de red - {str(e)[:50]}"
            if attempt < MAX_RETRIES:
                await context.bot.edit_message_text(
                    text=f"🌐 Error de red coño...\n🔄 Reintentando ({attempt}/{MAX_RETRIES})...\n⏳ Esperando {RETRY_DELAY * attempt}s...",
                    chat_id=chat_id,
                    message_id=message_id
                )
                await asyncio.sleep(RETRY_DELAY * attempt)

        except TelegramError as e:
            logger.error(f"Telegram error on attempt {attempt}: {e}")
            last_error = f"Error de Telegram - {str(e)[:50]}"
            if "file is too big" in str(e).lower():
                last_error = "Archivo muy grande para Telegram (>2GB)"
                break  # Don't retry if file is too big
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)

        except Exception as e:
            logger.error(f"Unexpected error on attempt {attempt}: {e}")
            last_error = f"Error inesperado - {str(e)[:50]}"
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)

    # All retries failed
    logger.error(f"Failed to upload {filename} after {MAX_RETRIES} attempts")
    await context.bot.edit_message_text(
        text=f"❌ **Error subiendo archivo**\n\n"
             f"📦 Archivo: `{filename}`\n"
             f"❗ Error: {last_error}\n\n"
             f"El archivo sigue en el servidor, intenta de nuevo más tarde.",
        chat_id=chat_id,
        message_id=message_id,
        parse_mode='Markdown'
    )
    return False


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

        # Upload files with progress and retry
        total_files = len(files_to_upload)
        upload_success = True

        for idx, file_to_upload in enumerate(files_to_upload):
            part_info = f" (Parte {idx+1}/{total_files})" if total_files > 1 else ""

            logger.info(f"Starting upload of {file_to_upload}")
            success = await upload_file_with_retry(
                context=context,
                chat_id=chat_id,
                file_path=file_to_upload,
                message_id=message.message_id,
                is_video=is_video_file(file_to_upload),
                part_info=part_info
            )

            if not success:
                upload_success = False
                logger.error(f"Failed to upload {file_to_upload}")
                break

        if upload_success:
            await context.bot.edit_message_text(
                text="✅ **¡Todo listo marico!**\n\nArchivo subido exitosamente (｡◕‿◕｡)",
                chat_id=chat_id,
                message_id=message.message_id,
                parse_mode='Markdown'
            )
            await asyncio.sleep(3)
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            except:
                pass

    except Exception as e:
        logger.error(f"Error in download_torrent_and_upload: {e}")
        await context.bot.send_message(
            chat_id,
            f"❌ **Error procesando torrent**\n\n"
            f"❗ {str(e)[:200]}\n\n"
            f"El archivo puede seguir en el servidor.",
            parse_mode='Markdown'
        )
    finally:
        # Clean up all files
        try:
            if file_size > MAX_FILE_SIZE:
                for f in files_to_upload:
                    if os.path.exists(f):
                        os.remove(f)
                        logger.info(f"Cleaned up {f}")

            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up {file_path}")
        except Exception as cleanup_error:
            logger.error(f"Error during cleanup: {cleanup_error}")

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

        # Upload files with progress and retry
        total_files = len(files_to_upload)
        upload_success = True

        for idx, file_to_upload in enumerate(files_to_upload):
            part_info = f" (Parte {idx+1}/{total_files})" if total_files > 1 else ""

            logger.info(f"Starting upload of {file_to_upload}")
            success = await upload_file_with_retry(
                context=context,
                chat_id=chat_id,
                file_path=file_to_upload,
                message_id=message.message_id,
                is_video=is_video_file(file_to_upload),
                part_info=part_info
            )

            if not success:
                upload_success = False
                logger.error(f"Failed to upload {file_to_upload}")
                break

        if upload_success:
            await context.bot.edit_message_text(
                text="✅ **¡Todo listo marico!**\n\nArchivo de MediaFire subido exitosamente (｡◕‿◕｡)",
                chat_id=chat_id,
                message_id=message.message_id,
                parse_mode='Markdown'
            )
            await asyncio.sleep(3)
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            except:
                pass

    except Exception as e:
        logger.error(f"Error in download_mediafire_and_upload: {e}")
        await context.bot.send_message(
            chat_id,
            f"❌ **Error con MediaFire**\n\n"
            f"❗ {str(e)[:200]}\n\n"
            f"El archivo puede seguir en el servidor.",
            parse_mode='Markdown'
        )
    finally:
        # Clean up all files
        try:
            if file_size > MAX_FILE_SIZE:
                for f in files_to_upload:
                    if os.path.exists(f):
                        os.remove(f)
                        logger.info(f"Cleaned up {f}")

            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Cleaned up {filepath}")
        except Exception as cleanup_error:
            logger.error(f"Error during cleanup: {cleanup_error}")


# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text(
        "¡Épale marico! Bot de descargas a la orden ✨\n\n"
        "Mándame:\n"
        "- Un enlace magnet para bajar torrents\n"
        "- Un enlace de MediaFire para bajar archivos\n\n"
        "Comandos:\n"
        "- /list - Ver archivos descargados\n"
        "- /upload <nombre> - Subir archivo existente\n\n"
        "Los videos los subo como media comprimida papa.\n"
        "Si pesa más de 2GB, lo parto en pedazos verga.\n\n"
        "Dale pues, manda ese enlace que yo te lo bajo (｡◕‿◕｡)"
    )


async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List downloaded files."""
    chat_id = update.effective_chat.id
    download_dir = '/downloads'

    try:
        files = []
        for f in os.listdir(download_dir):
            filepath = os.path.join(download_dir, f)
            if os.path.isfile(filepath) and not f.endswith('.binlog'):
                size = os.path.getsize(filepath)
                size_str = f"{size / (1024**3):.2f}GB" if size >= 1024**3 else f"{size / (1024**2):.1f}MB"
                files.append(f"📦 `{f}`\n   └─ {size_str}")

        if files:
            file_list = "\n\n".join(files)
            await update.message.reply_text(
                f"📂 **Archivos en /downloads:**\n\n{file_list}\n\n"
                f"💡 Usa `/upload <nombre>` para subir",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("📂 No hay archivos descargados marico")

    except Exception as e:
        logger.error(f"Error listing files: {e}")
        await update.message.reply_text(f"❌ Error listando archivos: {e}")


async def upload_existing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Upload an existing file from downloads."""
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text(
            "❌ Falta el nombre del archivo marico\n\n"
            "Uso: `/upload nombre_archivo.mp4`\n"
            "Usa `/list` para ver archivos disponibles",
            parse_mode='Markdown'
        )
        return

    filename = ' '.join(context.args)
    filepath = os.path.join('/downloads', filename)

    if not os.path.exists(filepath):
        await update.message.reply_text(
            f"❌ No encontré el archivo `{filename}`\n\n"
            f"Usa `/list` para ver archivos disponibles",
            parse_mode='Markdown'
        )
        return

    # Get file info
    file_size = os.path.getsize(filepath)
    size_str = f"{file_size / (1024**3):.2f}GB" if file_size >= 1024**3 else f"{file_size / (1024**2):.1f}MB"
    is_video = is_video_file(filepath)
    file_type = "🎬 Video" if is_video else "📄 Documento"

    message = await context.bot.send_message(
        chat_id,
        f"📋 **Preparando archivo**\n\n"
        f"📦 `{filename}`\n"
        f"💾 Tamaño: {size_str}\n"
        f"📁 Tipo: {file_type}\n\n"
        f"⏳ Verificando archivo...",
        parse_mode='Markdown'
    )

    try:
        files_to_upload = []

        # Check if splitting is needed
        if file_size > MAX_FILE_SIZE:
            await context.bot.edit_message_text(
                text=f"📋 **Preparando archivo**\n\n"
                     f"📦 `{filename}`\n"
                     f"💾 Tamaño: {size_str}\n"
                     f"📁 Tipo: {file_type}\n\n"
                     f"⚠️ Archivo muy grande (>{MAX_FILE_SIZE/(1024**3):.0f}GB)\n"
                     f"✂️ Dividiendo en partes...\n\n"
                     f"[░░░░░░░░░░] 0%",
                chat_id=chat_id,
                message_id=message.message_id,
                parse_mode='Markdown'
            )

            if is_video:
                files_to_upload = split_video_ffmpeg(filepath)
            else:
                files_to_upload = split_file_zip(filepath)

            await context.bot.edit_message_text(
                text=f"📋 **Preparando archivo**\n\n"
                     f"📦 `{filename}`\n"
                     f"💾 Tamaño: {size_str}\n"
                     f"📁 Tipo: {file_type}\n\n"
                     f"✅ Dividido en {len(files_to_upload)} partes\n\n"
                     f"[██████████] 100%",
                chat_id=chat_id,
                message_id=message.message_id,
                parse_mode='Markdown'
            )
        else:
            files_to_upload = [filepath]
            await context.bot.edit_message_text(
                text=f"📋 **Preparando archivo**\n\n"
                     f"📦 `{filename}`\n"
                     f"💾 Tamaño: {size_str}\n"
                     f"📁 Tipo: {file_type}\n\n"
                     f"✅ Archivo listo para subir\n\n"
                     f"[██████████] 100%",
                chat_id=chat_id,
                message_id=message.message_id,
                parse_mode='Markdown'
            )

        await asyncio.sleep(1)  # Brief pause before upload

        total_files = len(files_to_upload)
        upload_success = True

        for idx, file_to_upload in enumerate(files_to_upload):
            part_info = f" (Parte {idx+1}/{total_files})" if total_files > 1 else ""

            logger.info(f"Starting upload of {file_to_upload}")
            success = await upload_file_with_retry(
                context=context,
                chat_id=chat_id,
                file_path=file_to_upload,
                message_id=message.message_id,
                is_video=is_video_file(file_to_upload),
                part_info=part_info
            )

            if not success:
                upload_success = False
                logger.error(f"Failed to upload {file_to_upload}")
                break

        if upload_success:
            await context.bot.edit_message_text(
                text=f"✅ **¡Todo listo marico!**\n\n"
                     f"📦 `{filename}`\n"
                     f"💾 {size_str} subidos\n\n"
                     f"(｡◕‿◕｡) Archivo enviado exitosamente",
                chat_id=chat_id,
                message_id=message.message_id,
                parse_mode='Markdown'
            )
            await asyncio.sleep(3)
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            except:
                pass

    except Exception as e:
        logger.error(f"Error uploading existing file: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message.message_id,
            text=f"❌ **Error subiendo archivo**\n\n"
                 f"📦 `{filename}`\n"
                 f"❗ {str(e)[:200]}\n\n"
                 f"El archivo sigue en el servidor.",
            parse_mode='Markdown'
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
        .local_mode(True) \
        .http_version('1.1') \
        .get_updates_http_version('1.1') \
        .build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", list_files))
    application.add_handler(CommandHandler("upload", upload_existing))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Run the bot until the user presses Ctrl-C
    application.run_polling()

if __name__ == '__main__':
    main()
