import os
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
import asyncio
import sys

# Load environment variables
load_dotenv()
API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH', '')

# Phone number to authenticate
PHONE = os.getenv('Phone_number', '')   # Make sure this is your number

# In-memory only authentication script
async def main():
    print(f"Starting in-memory authentication for {PHONE}")
    
    # Use StringSession (in-memory only, no file storage)
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    
    # Connect
    print("Connecting to Telegram...")
    await client.connect()
    
    if await client.is_user_authorized():
        print("You're already authorized!")
    else:
        print("Sending code request...")
        await client.send_code_request(PHONE)
        
        # Get code from user input
        code = input("Enter the code you received: ")
        
        try:
            print("Signing in...")
            await client.sign_in(phone=PHONE, code=code)
            print("Successfully authenticated!")
        except Exception as e:
            print(f"Error during authentication: {e}")
            return
    
    # Test that we can get some dialogs
    print("Testing connection by getting some dialogs...")
    async for dialog in client.iter_dialogs(limit=5):
        print(f"- {dialog.name}")
    
    # Get the session string to save
    session_string = client.session.save()
    
    # Save the session string to a file
    with open("session_string.txt", "w") as f:
        f.write(session_string)
    
    print("\nSession string saved to session_string.txt")
    print("You can now update bot.py to use this session string instead of file-based sessions.")
    
    # Disconnect properly
    await client.disconnect()
    print("Disconnected.")

if __name__ == "__main__":
    asyncio.run(main()) 