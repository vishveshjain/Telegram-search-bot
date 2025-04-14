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

async def main():
    print(f"Starting authentication for {PHONE}")
    
    # Delete existing session if it exists
    if os.path.exists(f"{PHONE}.session"):
        try:
            os.remove(f"{PHONE}.session")
            print(f"Removed existing session file: {PHONE}.session")
        except Exception as e:
            print(f"Could not remove session file: {e}")
    
    # Also remove journal files if they exist
    if os.path.exists(f"{PHONE}.session-journal"):
        try:
            os.remove(f"{PHONE}.session-journal")
            print(f"Removed existing journal file: {PHONE}.session-journal")
        except Exception as e:
            print(f"Could not remove journal file: {e}")
    
    # Create client with basic parameters - exactly like auth_simple.py
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
    print("Disconnected. Session file created successfully.")
    print(f"The bot.py will now use the session file: {PHONE}.session")
    
    # Print instructions to update bot.py
    print("\nTo update bot.py, edit these lines:")
    print("""
# Create directories for session files
os.makedirs("sessions", exist_ok=True)
os.makedirs("clean_sessions", exist_ok=True)

# Use the existing session file directly
user_client = TelegramClient(
    os.getenv('Phone_number', '') ,  # Use the phone number directly as session name
    API_ID,
    API_HASH
)
    """)

if __name__ == "__main__":
    asyncio.run(main()) 