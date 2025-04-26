from dotenv import load_dotenv
import os
import sys
from telethon.sync import TelegramClient

print('--- test.py start ---')
print("=== test.py debug start ===")
print("cwd:", os.getcwd())
print("__file__:", __file__)
print("exists:", os.path.exists(__file__))
# Load .env from project root
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))
API_ID = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH', '')
# Debug environment loading
print('API_ID:', API_ID)
print('API_HASH:', API_HASH)

# Use existing .session file for authentication
SESSION_PATH = os.path.join(os.path.dirname(__file__), '+919205010115.session')
client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
client.start()

# Fetch and print message
chat_id = 1520230767
message_id = 1608017
msg = client.get_messages(chat_id, ids=[message_id])
if isinstance(msg, (list, tuple)):
    msg = msg[0] if msg else None
print('Message:', msg)
print('Media:', getattr(msg, 'media', None))