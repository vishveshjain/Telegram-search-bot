import os
import re

def update_bot_py():
    print("Updating bot.py to use StringSession...")
    
    # Check if session string exists
    if not os.path.exists("session_string.txt"):
        print("Error: session_string.txt not found.")
        print("Please run memory_auth.py first to create a session string.")
        return
    
    # Read the session string
    with open("session_string.txt", "r") as f:
        session_string = f.read().strip()
    
    if not session_string:
        print("Error: session_string.txt is empty.")
        return
    
    # Read the bot.py file
    if not os.path.exists("bot.py"):
        print("Error: bot.py not found.")
        return
    
    with open("bot.py", "r", encoding="utf-8") as f:
        bot_code = f.read()
    
    # Create a backup
    with open("bot_backup.py", "w", encoding="utf-8") as f:
        f.write(bot_code)
    print("Created backup at bot_backup.py")
    
    # Replace the client initialization code
    new_client_code = f'''# Use StringSession with the saved session string
from telethon.sessions import StringSession
SESSION_STRING = "{session_string}"
user_client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH
)
'''
    
    # Pattern to match client initialization code
    pattern = r'# Use a simple approach to initialize.+?API_HASH\s+?\)\s+?except.+?raise  # Re-raise any other exception'
    
    # Replace the code
    new_bot_code = re.sub(pattern, new_client_code, bot_code, flags=re.DOTALL)
    
    # Write the updated code back to bot.py
    with open("bot.py", "w", encoding="utf-8") as f:
        f.write(new_bot_code)
    
    print("bot.py has been updated to use StringSession instead of file-based session.")
    print("You can now run the bot with: python bot.py")

if __name__ == "__main__":
    update_bot_py() 