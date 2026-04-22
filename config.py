import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN")

MANAGER = int(os.getenv("MANAGER"))
MANAGER_USER_NAME = os.getenv("MANAGER_USER_NAME")

# Webhook settings
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
PROXY_URL = os.getenv("PROXY_URL")

# URL для получения каталога из 1С
URL_1C = os.getenv("URL_1C")
