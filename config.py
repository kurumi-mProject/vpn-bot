import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
XRAY_CONFIG = os.getenv("XRAY_CONFIG")
SERVER_IP = os.getenv("SERVER_IP")
PUBLIC_KEY = os.getenv("PUBLIC_KEY")
SHORT_ID = os.getenv("SHORT_ID", "")
PRICE = int(os.getenv("PRICE", 250))
TRAFFIC_LIMIT_GB = int(os.getenv("TRAFFIC_LIMIT_GB", 100))
MTPROTO_LINK = "tg://proxy?server=46.226.164.14&port=2443&secret=ee1ebc8efa337b7f451ad5afdac8e56aba7777772e636c6f7564666c6172652e636f6d"

AITUNNEL_KEY = "sk-aitunnel-awaoEKaloUAuZ7pALMMN8VB7GCKRgm6v"
AITUNNEL_URL = "https://api.aitunnel.ru/v1/chat/completions"
GPT_MODEL    = "grok-4.1-fast"

# Лимиты трафика по тарифам (ГБ/мес)
TRAFFIC_LIMITS = {1: 100, 3: 150, 6: 200, 12: 300}