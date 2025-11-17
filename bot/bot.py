import os
import asyncio
import libtorrent as lt
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Get the bot token from the environment variable
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables")

# --- Torrent Download Logic ---
async def download_torrent_and_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, magnet_link: str):
    """Downloads a torrent from a magnet link and uploads the largest file to Telegram."""
    chat_id = update.effective_chat.id
    ses = lt.session()
    ses.listen_on(6881, 6891)
    params = lt.parse_magnet_uri(magnet_link)
    params.save_path = '/downloads'
    handle = ses.add_torrent(params)

    message = await context.bot.send_message(chat_id, "Starting download...")

    while not handle.has_metadata():
        await asyncio.sleep(1)

    torinfo = handle.get_torrent_info()
    largest_file = max(torinfo.files(), key=lambda f: f.size)
    file_path = os.path.join(params.save_path, largest_file.path)

    while not handle.status().is_seeding:
        s = handle.status()
        state_str = ['queued', 'checking', 'downloading metadata', 'downloading', 'finished', 'seeding', 'allocating']
        progress = s.progress * 100
        
        status_text = (
            f"Downloading: {torinfo.name()}\n"
            f"{state_str[s.state]} {progress:.2f}% "
            f"({s.download_rate / 1000:.1f} kB/s down, {s.upload_rate / 1000:.1f} kB/s up)"
            f"Peers: {s.num_peers}"
        )
        
        await context.bot.edit_message_text(text=status_text, chat_id=chat_id, message_id=message.message_id)
        await asyncio.sleep(5)

    await context.bot.edit_message_text(text="Download finished. Starting upload...", chat_id=chat_id, message_id=message.message_id)

    try:
        await context.bot.send_document(chat_id, document=open(file_path, 'rb'), read_timeout=120, write_timeout=120, connect_timeout=120)
        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
    except Exception as e:
        await context.bot.send_message(chat_id, f"Failed to upload file: {e}")
    finally:
        # Clean up the downloaded file
        if os.path.exists(file_path):
            os.remove(file_path)
        ses.remove_torrent(handle)


# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text(
        "Welcome to the Torrent Downloader Bot!\n"
        "Send me a magnet link to start downloading."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming messages and starts the torrent download if it's a magnet link."""
    text = update.message.text
    if text.startswith("magnet:?"):
        await download_torrent_and_upload(update, context, text)
    else:
        await update.message.reply_text("Please send a valid magnet link.")

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
