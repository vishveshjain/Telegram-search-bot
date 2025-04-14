import os
from dotenv import load_dotenv
from telethon import TelegramClient
import asyncio
import sys

# Load environment variables
load_dotenv()
API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH', '')

# Phone number to authenticate
PHONE = os.getenv('Phone_number', '')   # Make sure this is your number

# Super simple authentication script
async def main():
    print(f"Starting simple authentication for {PHONE}")
    
    # Delete existing session if it exists
    if os.path.exists(f"{PHONE}.session"):
        try:
            os.remove(f"{PHONE}.session")
            print(f"Removed existing session file: {PHONE}.session")
        except Exception as e:
            print(f"Could not remove session file: {e}")
    
    # Create client with basic parameters
    client = TelegramClient(PHONE, API_ID, API_HASH)
    
    # Connect
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
    
    # Disconnect properly
    await client.disconnect()
    print("Disconnected. Session file should be created successfully.")
    print(f"You can now run the bot.py which will use the session file: {PHONE}.session")

if __name__ == "__main__":
    asyncio.run(main()) 