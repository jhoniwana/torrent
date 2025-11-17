# Torrent and MediaFire Telegram Bot

This project provides a Telegram bot that can download files from magnet links (torrents) and MediaFire URLs, and then upload them to Telegram. It includes features for handling large files by splitting them into multiple parts if they exceed Telegram's 2GB limit.

## Features

-   **Torrent Downloads**: Download files directly from magnet links.
-   **MediaFire Downloads**: Download files from MediaFire URLs.
-   **Large File Handling**: Automatically splits files larger than 2GB into multiple parts for successful upload to Telegram.
    -   Video files are split using `ffmpeg`.
    -   Other file types are split and compressed into `.zip` archives.
-   **Progress Bar**: Provides a "kawaii" (cute) progress bar with "maracucho" (Venezuelan regional slang) accent during downloads.

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes.

### Prerequisites

Before you begin, ensure you have the following installed:

-   [Docker](https://docs.docker.com/get-docker/)
-   [Docker Compose](https://docs.docker.com/compose/install/)

### Installation and Setup

1.  **Clone the repository (if you haven't already):**
    ```bash
    git clone <your-repository-url>
    cd torrent
    ```

2.  **Obtain API Credentials:**
    *   **Telegram API ID and Hash**: Go to [my.telegram.org](https://my.telegram.org/) and log in with your Telegram account. You will find your `API ID` and `API HASH` there.
    *   **Bot Token**: Talk to [@BotFather](https://t.me/BotFather) on Telegram, create a new bot, and he will give you a `BOT_TOKEN`.

3.  **Configure Environment Variables:**
    Rename `.env.example` to `.env` and fill in your credentials:
    ```bash
    mv .env.example .env
    ```
    Edit the `.env` file:
    ```ini
    TELEGRAM_API_ID=YOUR_API_ID
    TELEGRAM_API_HASH=YOUR_API_HASH
    BOT_TOKEN=YOUR_BOT_TOKEN
    ```
    Replace `YOUR_API_ID`, `YOUR_API_HASH`, and `YOUR_BOT_TOKEN` with the values you obtained.

4.  **Build and Run with Docker Compose:**
    Navigate to the root directory of the project (where `docker-compose.yml` is located) and run:
    ```bash
    docker-compose up --build -d
    ```
    This command will:
    *   Build the `torrent-bot` Docker image.
    *   Start the `telegram-bot-api` service (a local Telegram Bot API server).
    *   Start the `torrent-bot` service, which runs your Python bot.
    *   The `-d` flag runs the services in detached mode (in the background).

5.  **Verify Installation:**
    You can check the logs of your services to ensure they are running correctly:
    ```bash
    docker-compose logs -f
    ```
    Look for messages indicating that the bot has started successfully.

## Usage

Once the bot is running, you can interact with it on Telegram:

1.  **Start the bot**: Send the `/start` command to your bot on Telegram. It will greet you with a welcome message and instructions.
2.  **Download a Torrent**: Send a `magnet:?` link directly to the bot.
    Example: `magnet:?xt=urn:btih:YOUR_TORRENT_HASH&dn=Your.Torrent.Name`
3.  **Download from MediaFire**: Send a MediaFire URL directly to the bot.
    Example: `https://www.mediafire.com/file/yourfile.zip/file`

The bot will provide progress updates during the download and upload process.

## Project Structure

-   `.env.example`: Example environment variables file.
-   `.gitignore`: Specifies intentionally untracked files to ignore.
-   `CLAUDE.md`: (Possibly a document related to Claude AI, if used in development).
-   `docker-compose.yml`: Defines the services for running the bot and a local Telegram Bot API server.
-   `bot/`: Contains the Python bot application.
    -   `bot.py`: The main script for the Telegram bot logic.
    -   `requirements.txt`: Python dependencies for the bot.
    -   `Dockerfile`: Instructions to build the Docker image for the bot.
-   `downloads/`: A volume mounted directory where downloaded files are temporarily stored.

## Making the Repository Public

To make your Git repository public, you need to do this through your Git hosting service (e.g., GitHub, GitLab, Bitbucket). This CLI cannot directly change the visibility settings of your remote repository.

Here are general steps for common platforms:

### GitHub

1.  Go to your repository on GitHub.
2.  Click on the **Settings** tab.
3.  Scroll down to the "Danger Zone" section.
4.  Click on **Change repository visibility**.
5.  Select **Public** and confirm your choice.

### GitLab

1.  Go to your project on GitLab.
2.  In the left sidebar, go to **Settings > General**.
3.  Expand the **Visibility, project features, permissions** section.
4.  Under "Project visibility", select **Public**.
5.  Click **Save changes**.

### Bitbucket

1.  Go to your repository on Bitbucket.
2.  Click on **Repository settings** in the left sidebar.
3.  Under "General", find the "Access level" section.
4.  Change the access level to **Public**.
5.  Click **Save**.

Remember that making your repository public means anyone on the internet can see your code. Ensure you have not committed any sensitive information (like API keys or personal data) directly into your code before making it public. The `.env` file (which is ignored by `.gitignore`) is the correct place for such sensitive information.
