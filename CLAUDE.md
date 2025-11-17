# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Telegram bot that downloads files from magnet links (torrents) and MediaFire, then uploads them to Telegram. Features include:
- Torrent downloads via magnet links
- MediaFire file downloads
- Automatic file splitting for files >2GB (using ffmpeg for videos, zip for other files)
- Videos uploaded as compressed media instead of documents
- Kawaii progress bars with Venezuelan "maracucho" accent
- Silent operation in groups (only responds to valid links, no flood)

## Architecture

The project consists of two Docker services:

1. **telegram-bot-api**: Local Telegram Bot API server (aiogram/telegram-bot-api)
   - Runs on port 8081
   - Required for uploading large files (>50MB) to Telegram
   - Stores bot data in `/var/lib/telegram-bot-api` (mapped to `./downloads`)

2. **torrent-bot**: Python bot application
   - Uses `python-telegram-bot` library for Telegram integration
   - Uses `libtorrent` for torrent downloading
   - Uses `requests` and `BeautifulSoup` for MediaFire scraping
   - Uses `ffmpeg` for video splitting
   - Downloads files to `/downloads` directory
   - Automatically finds and uploads the largest file from torrents
   - Splits files >2GB automatically
   - Cleans up files after upload

## Development Commands

### Running the application
```bash
# Start both services
docker-compose up -d

# View logs
docker-compose logs -f

# Rebuild after code changes
docker-compose up -d --build
```

### Environment setup
Required environment variables (see `.env.example`):
- `TELEGRAM_API_ID`: Get from my.telegram.org
- `TELEGRAM_API_HASH`: Get from my.telegram.org
- `BOT_TOKEN`: Get from @BotFather on Telegram

### Testing the bot
Send links directly to the bot in Telegram:

**For magnet links:**
1. Bot downloads the torrent with progress updates
2. Extracts the largest file
3. Splits if >2GB (ffmpeg for videos, zip for others)
4. Uploads to Telegram (videos as media, others as documents)
5. Cleans up files

**For MediaFire links:**
1. Bot scrapes the MediaFire page to find download link
2. Downloads file with progress bar
3. Splits if >2GB
4. Uploads to Telegram
5. Cleans up files

**Note:** Bot only responds to valid magnet/MediaFire links to avoid flooding in groups.

## Key Implementation Details

### Bot Communication Flow
- Bot connects to local Bot API server at `http://telegram-bot-api:8081` instead of official Telegram API
- This allows uploading files larger than 50MB (up to 2GB)
- Both services must be running for the bot to function

### Download Processes

**Torrent downloads:**
- libtorrent session listens on ports 6881-6891
- Downloads to `/downloads` directory (shared volume)
- Kawaii progress bar updates every 5 seconds with download stats
- Only the largest file is uploaded (useful for multi-file torrents)

**MediaFire downloads:**
- Scrapes download page using BeautifulSoup
- Shows progress bar updating every 5% downloaded
- Supports all MediaFire file types

### File Splitting (>2GB files)
- **Videos**: Split using ffmpeg by duration, preserving quality (bot.py:134-156)
- **Other files**: Split into zip archives (bot.py:158-185)
- Each part uploaded separately with part numbering

### Video Upload Behavior
- Videos detected by MIME type (bot.py:121-124)
- Uploaded using `send_video()` for compressed streaming (bot.py:269-277, 347-355)
- Non-videos uploaded using `send_document()`

### Bot Message Style
- All messages use Venezuelan "maracucho" accent with casual language
- Progress bars show kaomojis that change based on completion percentage (bot.py:24-49)
- Messages include colorful emojis for better visual feedback

### Anti-Flood Behavior
- Bot silently ignores messages that aren't magnet or MediaFire links (bot.py:396-405)
- No error messages for invalid input to prevent spam in groups
- Only `/start` command and valid links trigger responses

### File Management
- Files are automatically deleted after successful upload
- Torrent session is cleaned up after each download
- Downloads persist in `./downloads` on host if upload fails

## Modifying the Bot

### Changing message style
Edit the progress bar function (bot.py:24-49) or individual message strings throughout the file.

### Adding new download sources
Add URL detection in `handle_message()` (bot.py:396-405) and create a new download function similar to `download_mediafire()` or `download_torrent_and_upload()`.

### Adjusting file splitting threshold
Change `MAX_FILE_SIZE` constant (bot.py:21) - currently set to 2GB.

### Modifying video detection
Edit `is_video_file()` function (bot.py:121-124) to change which files are uploaded as videos vs documents.

### Changing file selection for torrents
The largest file is selected in bot.py:219. Modify this logic to upload specific file types or all files.
