import os
import hashlib
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telethon import TelegramClient
from telethon.tl.types import InputPeerChannel, InputPeerChat
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.errors import ChannelPrivateError, ChatAdminRequiredError, PhoneNumberInvalidError, PhoneCodeInvalidError, SessionPasswordNeededError, PasswordHashInvalidError, PhoneCodeExpiredError, FloodWaitError, PhoneNumberBannedError
import pymongo
from fuzzywuzzy import fuzz
from telethon import events
import re
import time
import asyncio
from telethon.sessions import StringSession

# Load environment variables
load_dotenv()
API_ID = int(os.getenv('API_ID', 0))  # Convert to integer with fallback
API_HASH = os.getenv('API_HASH', '')
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')

# Verify credentials are loaded
if not API_ID or not API_HASH or not BOT_TOKEN:
    raise ValueError("Missing Telegram API credentials. Please check your .env file.")

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB configuration
mongo_available = True
logger.info("MongoDB support is enabled")

# Initialize MongoDB collections
if mongo_available:
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            client.admin.command('ping')  # Check if MongoDB is running
            db = client['telegram_search_bot']
            documents_collection = db['documents']
            users_collection = db['users']
            sources_collection = db['sources']
            
            # Test a simple query to verify collections work
            users_count = users_collection.count_documents({})
            logger.info(f"MongoDB connection successful. Users found: {users_count}")
            break
        except Exception as e:
            retry_count += 1
            logger.error(f"MongoDB connection attempt {retry_count} failed: {e}")
            if retry_count == max_retries:
                logger.error("All MongoDB connection attempts failed. Running in limited mode.")
                mongo_available = False
            else:
                # Wait before retrying
                time.sleep(1)

# Create dummy collections if MongoDB is not available
if not mongo_available:
    logger.warning("MongoDB is not available. Running in limited mode without database support.")
    class DummyCollection:
        def __init__(self):
            self.data = []
        
        def find(self, query=None):
            return DummyResults([])
        
        def find_one(self, query=None):
            return None
        
        def update_one(self, query, update, upsert=False):
            return None
        
        def insert_one(self, document):
            class DummyInsertResult:
                def __init__(self):
                    self.inserted_id = "dummy_id"
            return DummyInsertResult()
            
        def count(self):
            return 0
    
    class DummyResults:
        def __init__(self, results):
            self.results = results
        
        def sort(self, *args, **kwargs):
            return self
        
        def limit(self, n):
            return self
        
        def count(self):
            return len(self.results)
        
        def __iter__(self):
            return iter(self.results)
    
    documents_collection = DummyCollection()
    users_collection = DummyCollection()
    sources_collection = DummyCollection()

# Create directories for session files
os.makedirs("sessions", exist_ok=True)
os.makedirs("clean_sessions", exist_ok=True)

# Use a simple approach to initialize the client with phone number as session name
session_file = os.getenv('Phone_number', '') 
try:
    # Try to use file-based session first
    user_client = TelegramClient(
        session_file,
        API_ID,
        API_HASH
    )
except Exception as e:
    if "database is locked" in str(e):
        logger.warning("Session database is locked, using in-memory session instead")
        # Use in-memory session as fallback
        user_client = TelegramClient(
            StringSession(),  # In-memory session
            API_ID,
            API_HASH
        )
    else:
        raise  # Re-raise any other exception

# Constants for user state
AWAITING_SOURCE = "awaiting_source"
AWAITING_SEARCH = "awaiting_search"
AWAITING_PHONE = "awaiting_phone"
AWAITING_CODE = "awaiting_code"
AWAITING_2FA = "awaiting_2fa"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    if mongo_available:
        try:
            # Update user info in MongoDB
            users_collection.update_one(
                {'user_id': update.effective_user.id},
                {
                    '$set': {
                        'username': update.effective_user.username,
                        'first_name': update.effective_user.first_name,
                        'last_name': update.effective_user.last_name,
                        'last_active': datetime.now()
                    }
                },
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error updating user info: {str(e)}")
    
    # Create keyboard with options
    keyboard = [
        [
            InlineKeyboardButton("Connect to Channel/Group", callback_data="connect"),
            InlineKeyboardButton("Authenticate User", callback_data="auth_user")
        ],
        [
            InlineKeyboardButton("Search Documents", callback_data="search"),
            InlineKeyboardButton("Recent Documents", callback_data="recent")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Welcome message in English and Hindi
    welcome_message = (
        f"Hello {update.effective_user.first_name}! Welcome to the Telegram Document Search Bot.\n\n"
        "This bot helps you search for documents shared in Telegram channels and groups.\n"
        "To access message history, you'll need to authenticate with your user account.\n\n"
        f"नमस्ते {update.effective_user.first_name}! टेलीग्राम डॉक्यूमेंट सर्च बॉट में आपका स्वागत है।\n\n"
        "यह बॉट आपको टेलीग्राम चैनल और ग्रुप में शेयर किए गए दस्तावेज़ों को खोजने में मदद करता है।\n"
        "मैसेज हिस्ट्री तक पहुंचने के लिए, आपको अपने यूजर अकाउंट से ऑथेंटिकेट करने की आवश्यकता होगी।"
    )
    
    # Add warning about MongoDB if not available
    if not mongo_available:
        welcome_message += (
            "\n\n⚠️ MongoDB is not available. Some features will be limited.\n"
            "⚠️ MongoDB उपलब्ध नहीं है। कुछ सुविधाएँ सीमित होंगी।"
        )
    
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_text = (
        "This bot helps you search for documents in Telegram channels and groups.\n\n"
        "To use this bot effectively:\n"
        "1. First authenticate your user account to access message history\n"
        "2. Connect to channels or groups you want to index\n"
        "3. Search for documents by keywords\n\n"
        "Available commands:\n"
        "/start - Start the bot and see the main menu\n"
        "/auth - Authenticate your user account\n"
        "/connect - Connect to a channel or group\n"
        "/search - Search for documents\n"
        "/recent - View recent documents\n"
        "/help - Show this help message\n\n"
        "इस बॉट की मदद से आप टेलीग्राम चैनल और ग्रुप में दस्तावेज़ खोज सकते हैं।\n\n"
        "इस बॉट का प्रभावी ढंग से उपयोग करने के लिए:\n"
        "1. मैसेज हिस्ट्री तक पहुंचने के लिए पहले अपने यूजर अकाउंट को ऑथेंटिकेट करें\n"
        "2. जिन चैनल या ग्रुप को इंडेक्स करना चाहते हैं उनसे कनेक्ट करें\n"
        "3. कीवर्ड द्वारा दस्तावेज़ खोजें\n\n"
        "उपलब्ध कमांड्स:\n"
        "/start - बॉट शुरू करें और मुख्य मेनू देखें\n"
        "/auth - अपने यूजर अकाउंट को ऑथेंटिकेट करें\n"
        "/connect - किसी चैनल या ग्रुप से कनेक्ट करें\n"
        "/search - दस्तावेज़ खोजें\n"
        "/recent - हाल के दस्तावेज़ देखें\n"
        "/help - यह सहायता संदेश दिखाएं"
    )
    
    await update.message.reply_text(help_text)

async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start user authentication process with a simpler approach."""
    # Check if update is from callback or command
    if update.callback_query:
        message = update.callback_query.message
    else:
        message = update.message
    
    # Add proper warning about security
    auth_message = (
        "To access message history, you need to authenticate with your Telegram account.\n\n"
        "Please send your phone number in international format (e.g., +1234567890).\n"
        "Your credentials won't be stored - they're only used to create a session file.\n\n"
        "मैसेज हिस्ट्री तक पहुंचने के लिए, आपको अपने टेलीग्राम अकाउंट से ऑथेंटिकेट करने की आवश्यकता है।\n\n"
        "कृपया अपना फोन नंबर अंतरराष्ट्रीय प्रारूप में भेजें (जैसे, +1234567890)।\n"
        "आपके क्रेडेंशियल्स स्टोर नहीं किए जाएंगे - वे केवल एक सेशन फाइल बनाने के लिए उपयोग किए जाते हैं।"
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(auth_message)
    else:
        await message.reply_text(auth_message)
    
    # Set user state to waiting for phone number
    context.user_data['state'] = AWAITING_PHONE
    
    # Also store state in database for persistence
    if mongo_available:
        users_collection.update_one(
            {"user_id": update.effective_user.id},
            {"$set": {"state": AWAITING_PHONE}},
            upsert=True
        )
        logger.info(f"User state updated to AWAITING_PHONE for user {update.effective_user.id}")

async def connect_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start process to connect to a new channel or group."""
    await update.message.reply_text(
        "Please send me the username or link of the Telegram channel or group you want to connect to.\n"
        "For example: @channel_name or https://t.me/channel_name\n\n"
        "Note: Due to Telegram API limitations, I can only process NEW files posted in the channel/group AFTER I've been added.\n"
        "I won't be able to access message history or files uploaded before this point.\n\n"
        "कृपया उस टेलीग्राम चैनल या ग्रुप का यूजरनेम या लिंक भेजें जिससे आप जुड़ना चाहते हैं।\n"
        "उदाहरण के लिए: @channel_name या https://t.me/channel_name\n\n"
        "नोट: टेलीग्राम API की सीमाओं के कारण, मैं केवल उन नई फ़ाइलों को प्रोसेस कर सकता हूं जो मेरे जुड़ने के बाद चैनल/ग्रुप में पोस्ट की जाएंगी।\n"
        "मैं मैसेज हिस्ट्री या पहले अपलोड की गई फ़ाइलों को नहीं देख पाऊंगा।"
    )
    context.user_data['state'] = AWAITING_SOURCE

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start process to search for documents."""
    if not mongo_available:
        await update.message.reply_text(
            "Sorry, search functionality requires MongoDB which is not currently available.\n"
            "Please install and start MongoDB to enable full functionality.\n\n"
            "क्षमा करें, खोज कार्यक्षमता के लिए MongoDB की आवश्यकता है जो वर्तमान में उपलब्ध नहीं है।\n"
            "पूर्ण कार्यक्षमता सक्षम करने के लिए कृपया MongoDB इंस्टॉल करें और शुरू करें।"
        )
        return
        
    logger.info(f"Starting search for user_id: {update.effective_user.id}")
    user_sources = list(sources_collection.find({'user_id': update.effective_user.id}))
    logger.info(f"Found {len(user_sources)} sources for user")
    
    if not user_sources:
        await update.message.reply_text(
            "You haven't connected to any channels or groups yet. Use /connect first.\n\n"
            "आपने अभी तक किसी चैनल या ग्रुप से कनेक्ट नहीं किया है। पहले /connect का उपयोग करें।"
        )
        return
    
    await update.message.reply_text(
        "Please enter keywords to search for documents.\n\n"
        "कृपया दस्तावेज़ों की खोज के लिए कीवर्ड दर्ज करें।"
    )
    context.user_data['state'] = AWAITING_SEARCH

async def search_in_sources(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    """Search for documents in user's sources."""
    user_id = update.effective_user.id
    
    logger.info(f"Searching for query: '{query}' for user: {user_id}")
    
    # Search for documents matching the query
    results = search_documents(user_id, query)
    
    logger.info(f"Search results: {len(results)} documents found")
    
    if not results:
        await update.message.reply_text(
            f"No documents found matching '{query}'. Try a different search term.\n\n"
            f"'{query}' से मिलते जुलते कोई दस्तावेज़ नहीं मिले। कोई अलग खोज शब्द आज़माएं।"
        )
        return
    
    # Display results
    result_message = f"Found {len(results)} documents matching '{query}':\n\n"
    hindi_message = f"'{query}' से मिलते जुलते {len(results)} दस्तावेज़ मिले:\n\n"
    
    for i, doc in enumerate(results[:10], 1):  # Limit to first 10 results
        score = doc.get('match_score', 0)
        file_type = doc.get('file_type', 'unknown')
        result_message += f"{i}. {doc['file_name']} ({file_type}) - Match: {score}%\n"
        hindi_message += f"{i}. {doc['file_name']} ({file_type}) - मैच: {score}%\n"
    
    if len(results) > 10:
        result_message += f"\n... and {len(results) - 10} more results."
        hindi_message += f"\n... और {len(results) - 10} अधिक परिणाम।"
    
    await update.message.reply_text(result_message)
    await update.message.reply_text(hindi_message)

async def recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show recent documents."""
    if not mongo_available:
        await update.message.reply_text(
            "Sorry, this functionality requires MongoDB which is not currently available.\n"
            "Please install and start MongoDB to enable full functionality.\n\n"
            "क्षमा करें, इस कार्यक्षमता के लिए MongoDB की आवश्यकता है जो वर्तमान में उपलब्ध नहीं है।\n"
            "पूर्ण कार्यक्षमता सक्षम करने के लिए कृपया MongoDB इंस्टॉल करें और शुरू करें।"
        )
        return
        
    user_id = update.effective_user.id
    recent_docs = documents_collection.find(
        {'user_id': user_id}
    ).sort('date', -1).limit(10)
    
    recent_docs_list = list(recent_docs)
    if not recent_docs_list:
        await update.message.reply_text(
            "No documents found. Try connecting to a channel or group first.\n\n"
            "कोई दस्तावेज़ नहीं मिला। पहले किसी चैनल या ग्रुप से कनेक्ट करने का प्रयास करें।"
        )
        return
    
    message = "Recent documents:\n\n"
    hindi_message = "हाल के दस्तावेज़:\n\n"
    
    for doc in recent_docs_list:
        message += f"• {doc['file_name']} ({doc['file_type']})\n"
        hindi_message += f"• {doc['file_name']} ({doc['file_type']})\n"
    
    await update.message.reply_text(message)
    await update.message.reply_text(hindi_message)

def initialize_user(user_id):
    """Initialize a new user record."""
    user_data = {
        "user_id": user_id,
        "state": None,
        "authenticated": False,
        "created_at": datetime.now(),
        "last_active": datetime.now(),
        "sources": []
    }
    
    if mongo_available:
        users_collection.insert_one(user_data)
    
    return user_data

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle messages based on user state during authentication process."""
    global user_client
    
    user_id = update.effective_user.id
    message_text = update.message.text
    
    # Get user state from context or database
    user_state = None
    if context.user_data and "state" in context.user_data:
        user_state = context.user_data["state"]
    else:
        # Try to get state from database
        user_data = db.users.find_one({"user_id": user_id})
        if user_data and "state" in user_data:
            user_state = user_data["state"]
            context.user_data["state"] = user_state
    
    logger.info(f"Handle message from user {user_id} in state: {user_state}")
    
    # If user is in authentication flow
    if user_state == AWAITING_PHONE:
        phone_number = message_text.strip()
        
        # Validate phone number format
        if not phone_number.startswith('+'):
            await update.message.reply_text("Please enter your phone number with country code (e.g. +1234567890)")
            return
            
        try:
            # Try to remove any old session files that might be locked
            session_path = f"{phone_number}.session"
            if os.path.exists(session_path):
                try:
                    logger.info(f"Removing existing session file: {session_path}")
                    os.remove(session_path)
                except Exception as e:
                    logger.error(f"Could not remove session file: {e}")
            
            # Simple approach to authentication
            try:
                user_client = TelegramClient(phone_number, API_ID, API_HASH)
            except Exception as e:
                if "database is locked" in str(e):
                    logger.warning("Session database is locked, using in-memory session")
                    user_client = TelegramClient(StringSession(), API_ID, API_HASH)
                else:
                    raise
            
            # Connect the client
            await user_client.connect()
            
            # Check if already authorized
            if await user_client.is_user_authorized():
                await update.message.reply_text("You're already authorized! You can now use the bot.")
                context.user_data["state"] = None
                return
            
            # Send code request
            await update.message.reply_text("Sending verification code to your phone...")
            await user_client.send_code_request(phone_number)
            
            # Store the phone in context
            context.user_data["phone"] = phone_number
            
            # Update user state
            context.user_data["state"] = AWAITING_CODE
            
            # Store state in database if available
            if mongo_available:
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "phone": phone_number,
                        "state": AWAITING_CODE
                    }},
                    upsert=True
                )
            
            await update.message.reply_text(
                "Verification code has been sent to your Telegram app or SMS. "
                "Please enter the code without spaces or special characters."
            )
            
        except Exception as e:
            logger.error(f"Error in phone number stage: {str(e)}")
            await update.message.reply_text(f"Authentication error: {str(e)}")
            
    elif user_state == AWAITING_CODE:
        try:
            code = message_text.strip()
            
            # Basic validation - no spaces or special chars
            if not code.isdigit():
                await update.message.reply_text("Invalid code format. Please enter only the numbers from the verification code.")
                return
                
            phone = context.user_data.get("phone")
            
            if not phone:
                await update.message.reply_text("Session expired. Please start authentication again with /auth")
                return
            
            # Make sure client is connected
            if not user_client or not user_client.is_connected():
                # Simple approach to reconnect
                try:
                    # Try to reconnect with file session
                    user_client = TelegramClient(phone, API_ID, API_HASH)
                except Exception as e:
                    if "database is locked" in str(e):
                        # Fall back to in-memory session
                        logger.warning("Session database is locked, using in-memory session for code verification")
                        user_client = TelegramClient(StringSession(), API_ID, API_HASH)
                    else:
                        raise
                await user_client.connect()
            
            await update.message.reply_text("Verifying code... Please wait.")
            
            try:
                # Simple approach to sign in with the code
                await user_client.sign_in(phone=phone, code=code)
                
                # Successfully authenticated
                await update.message.reply_text(
                    "Authentication successful! ✅\n\n"
                    "You can now use the bot to search and fetch files from channels.\n\n"
                    "सत्यापन सफल! ✅\n\n"
                    "अब आप चैनलों से फ़ाइलें खोजने और प्राप्त करने के लिए बॉट का उपयोग कर सकते हैं।"
                )
                
                # Update user state
                context.user_data["state"] = None
                
                # Update database if available
                if mongo_available:
                    users_collection.update_one(
                        {"user_id": user_id},
                        {"$set": {
                            "state": None,
                            "is_authenticated": True,
                            "authenticated_at": datetime.now()
                        }},
                        upsert=True
                    )
                
            except Exception as e:
                logger.error(f"Error in code verification: {str(e)}")
                await update.message.reply_text(f"Error during verification: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error in code verification stage: {str(e)}")
            await update.message.reply_text(f"Error during verification: {str(e)}")
    
    # For authenticated users or users not in any state, provide help
    elif not user_state:
        # Default response for users not in any specific state
        await update.message.reply_text(
            "Welcome to Telegram Search Bot! Use /auth to log in with your Telegram account or /help for more information."
        )

async def connect_to_source(update: Update, context: ContextTypes.DEFAULT_TYPE, source_text: str) -> None:
    """Connect to a channel or group."""
    user_id = update.effective_user.id
    
    # Check if user is authenticated by checking if the global client is authorized
    is_authorized = False
    try:
        if user_client and user_client.is_connected():
            is_authorized = await user_client.is_user_authorized()
        
        if not is_authorized:
            # Try to connect the client if it's not already
            await user_client.connect()
            is_authorized = await user_client.is_user_authorized()
    except Exception as e:
        logger.error(f"Error checking authorization: {e}")
    
    if not is_authorized:
        await update.message.reply_text(
            "You need to authenticate first. Use /auth to connect your Telegram account.\n"
            "आपको पहले प्रमाणित करने की आवश्यकता है। अपने टेलीग्राम खाते को कनेक्ट करने के लिए /auth का उपयोग करें।"
        )
        return
        
    # Process source text - could be a username, invite link, or channel ID
    await update.message.reply_text(
        f"Connecting to {source_text}... Please wait.\n"
        f"{source_text} से कनेक्ट हो रहा है... कृपया प्रतीक्षा करें।"
    )
    
    try:
        # Try to resolve the source and add it to the user's sources
        result = await fetch_channel_content(user_id, source_text)
        
        if result:
            await update.message.reply_text(
                f"Successfully connected to {source_text}. {result['count']} messages indexed.\n"
                f"{source_text} सफलतापूर्वक जुड़ गए। {result['count']} संदेश अनुक्रमित।"
            )
        else:
            await update.message.reply_text(
                f"Failed to connect to {source_text}. Please check the source name/link and try again.\n"
                f"{source_text} को जोड़ने में विफल। कृपया स्रोत नाम/लिंक जांचें और पुनः प्रयास करें।"
            )
    except Exception as e:
        logger.error(f"Error connecting to source: {e}")
        await update.message.reply_text(
            f"Error: {str(e)}\n"
            f"त्रुटि: {str(e)}"
        )

async def fetch_channel_content(user_id, source_name, source_id=None):
    """Fetch content from a Telegram channel using user's authenticated session."""
    global user_client
    
    # Check if client is connected and authorized
    is_authorized = False
    try:
        if user_client and user_client.is_connected():
            is_authorized = await user_client.is_user_authorized()
        
        if not is_authorized:
            # Try to connect if not already
            await user_client.connect()
            is_authorized = await user_client.is_user_authorized()
    except Exception as e:
        logger.error(f"Error checking authorization in fetch_channel_content: {e}")
    
    if not is_authorized:
        logger.warning(f"User {user_id} not authorized, can't fetch channel content")
        return None
        
    try:
        logger.info(f"User client connected and authorized for user {user_id}")
        
        # Parse the input - could be username, invite link, or group/channel ID
        if source_name.startswith('https://t.me/'):
            # It's an invite link
            entity = await user_client.get_entity(source_name)
        else:
            # Try as username or ID
            try:
                entity = await user_client.get_entity(source_name)
            except:
                # If that fails, try as a chat ID
                try:
                    entity = await user_client.get_entity(int(source_name))
                except:
                    return None
        
        # Get the entity ID
        entity_id = entity.id
        
        # Fetch messages
        messages = []
        async for message in user_client.iter_messages(entity, limit=100):
            if message.text:
                # Create a unique ID for the message
                message_id = f"{entity_id}_{message.id}"
                message_hash = hashlib.md5(message.text.encode()).hexdigest()
                
                # Store in MongoDB
                message_data = {
                    "user_id": user_id,
                    "message_id": message_id,
                    "source_id": entity_id,
                    "source_name": getattr(entity, 'username', None) or getattr(entity, 'title', str(entity_id)),
                    "text": message.text,
                    "hash": message_hash,
                    "date": message.date,
                    "timestamp": datetime.now()
                }
                
                # Check if media exists
                if message.media:
                    message_data["has_media"] = True
                    # More media details can be added here
                
                # Save to MongoDB (update if exists)
                documents_collection.update_one(
                    {"message_id": message_id},
                    {"$set": message_data},
                    upsert=True
                )
                
                messages.append(message_data)
        
        # Add source to user's sources if not already there
        source_data = {
            "source_id": entity_id,
            "source_name": getattr(entity, 'username', None) or getattr(entity, 'title', str(entity_id)),
            "added_at": datetime.now()
        }
        
        users_collection.update_one(
            {"user_id": user_id},
            {"$addToSet": {"sources": source_data}}
        )
        
        return {"count": len(messages), "source": source_data}
    except Exception as e:
        logger.error(f"Error fetching channel content: {e}")
        return None

async def view_file(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str) -> None:
    """View a specific file."""
    # Handle file viewing logic here
    await update.callback_query.edit_message_text(
        f"File details for {file_id} would be shown here."
    )

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button clicks from inline keyboards."""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'connect':
        await connect_command(update, context)
    elif query.data == 'search':
        await search_command(update, context)
    elif query.data == 'recent':
        await recent_command(update, context)
    elif query.data == 'auth_user':
        await auth_command(update, context)
    elif query.data.startswith('view_'):
        # Extract file_id from callback data
        file_id = query.data.replace('view_', '')
        await view_file(update, context, file_id)
    else:
        await query.edit_message_text(
            text=f"Unknown button: {query.data}\n"
                 f"अज्ञात बटन: {query.data}"
        )

def search_documents(user_id, query):
    """Search for documents based on query."""
    if not mongo_available:
        logger.warning("MongoDB not available, can't search documents")
        return []
        
    # Get all documents for this user
    logger.info(f"Finding documents for user_id: {user_id}")
    
    try:
        user_docs = list(documents_collection.find({'user_id': user_id}))
        logger.info(f"Found {len(user_docs)} documents for user")
        
        # Calculate match scores
        results = []
        for doc in user_docs:
            try:
                # Search in file name
                file_name = doc.get('file_name', '')
                logger.debug(f"Checking document: {file_name}")
                
                if not file_name:
                    logger.warning(f"Document has no file_name: {doc}")
                    continue
                
                name_score = fuzz.partial_ratio(query.lower(), file_name.lower())
                
                # If we have content_searchable field, search there too
                content_score = 0
                if 'content_searchable' in doc and doc['content_searchable']:
                    content_score = fuzz.partial_ratio(query.lower(), doc['content_searchable'].lower())
                
                # Take the best match score
                score = max(name_score, content_score)
                logger.debug(f"Match score for {file_name}: {score}")
                
                # If score is above threshold, add to results
                if score > 60:  # Adjust threshold as needed
                    doc['match_score'] = score
                    results.append(doc)
            except Exception as e:
                logger.error(f"Error processing document {doc.get('_id')}: {str(e)}")
                continue
        
        # Sort by match score
        results.sort(key=lambda x: x['match_score'], reverse=True)
        
        # Return top results (limit to 20)
        return results[:20]
    except Exception as e:
        logger.error(f"Error during document search: {str(e)}")
        return []

async def process_new_message(event):
    """Process new messages in channels/groups the bot is monitoring."""
    if not mongo_available:
        return
        
    try:
        # Get the message
        message = event.message
        
        # Check if it contains media
        if message.media and hasattr(message.media, 'document'):
            # Get the chat where the message was sent
            chat = await event.get_chat()
            chat_username = chat.username if hasattr(chat, 'username') else str(chat.id)
            
            # Find sources that match this chat
            sources = list(sources_collection.find({'source_name': chat_username}))
            
            if not sources:
                # This channel isn't being monitored by any user
                return
                
            # Process the document for each user monitoring this channel
            doc = message.media.document
            
            # Get file attributes
            file_name = ""
            for attr in doc.attributes:
                if hasattr(attr, 'file_name'):
                    file_name = attr.file_name
                    break
            
            if not file_name:
                file_name = f"document_{doc.id}"
            
            # Determine file type
            file_type = ""
            if doc.mime_type:
                file_type = doc.mime_type.split('/')[1] if '/' in doc.mime_type else doc.mime_type
            else:
                # Try to get extension from file name
                if '.' in file_name:
                    file_type = file_name.split('.')[-1]
            
            # Calculate file hash for deduplication
            file_hash = hashlib.md5(str(doc.id).encode()).hexdigest()
            
            # Process for each user who is monitoring this channel
            for source in sources:
                user_id = source['user_id']
                source_id = source['_id']
                
                # Check if file already exists for this user
                existing_file = documents_collection.find_one({
                    'user_id': user_id,
                    'file_hash': file_hash
                })
                
                if not existing_file:
                    # Add file to database
                    documents_collection.insert_one({
                        'user_id': user_id,
                        'source_id': source_id,
                        'file_name': file_name,
                        'file_type': file_type,
                        'file_size': doc.size,
                        'file_hash': file_hash,
                        'message_id': message.id,
                        'date': message.date,
                        'content_searchable': file_name  # Basic searchable content
                    })
                    
                    # Increment the file count for this source
                    sources_collection.update_one(
                        {'_id': source_id},
                        {'$inc': {'total_files': 1}}
                    )
                    
                    logger.info(f"Processed new file: {file_name} for user {user_id}")
    
    except Exception as e:
        logger.error(f"Error processing new message: {str(e)}")

async def init_user_client(user_id, session_name=None, phone_number=None):
    """Initialize a Telethon client for the user.
    
    Args:
        user_id: Telegram user ID
        session_name: Optional custom session name
        phone_number: User's phone number (only needed for first authentication)
        
    Returns:
        bool: True if already authorized, False otherwise
    """
    global user_client
    
    # Generate a session path based on provided session name or default
    if not session_name:
        session_name = f"user_{user_id}"
    
    session_path = os.path.join('sessions', session_name)
    
    try:
        # Make sessions directory if it doesn't exist
        os.makedirs('sessions', exist_ok=True)
        
        # Check if existing session file and log its presence
        if os.path.exists(f"{session_path}.session"):
            logger.info(f"Using existing session file for user {user_id}")
        else:
            logger.info(f"No existing session file found for user {user_id}, creating new session")
        
        # Create client with iPad device parameters
        logger.info(f"Creating client with iPad device model for user {user_id}")
        user_client = TelegramClient(
            session_path,
            api_id=API_ID,
            api_hash=API_HASH
        )
        
        # Connect to Telegram
        logger.info(f"Connecting client for user {user_id}")
        await user_client.connect()
        logger.info(f"Connection successful for user {user_id}")
        
        # Check if already authorized
        is_authorized = await user_client.is_user_authorized()
        if is_authorized:
            logger.info(f"User {user_id} is already authorized with session {session_name}")
        else:
            logger.info(f"User {user_id} is not authorized yet, session {session_name}")
        
        return is_authorized
        
    except Exception as e:
        logger.error(f"Error initializing client for user {user_id}: {str(e)}")
        raise

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the Telegram bot."""
    logger.error(f"Exception while handling an update: {context.error}")
    
    # Get the exception
    error = context.error
    
    # Prepare the error message in English and Hindi
    error_message = "An error occurred. Please try again later."
    error_message_hindi = "एक त्रुटि हुई है। कृपया बाद में पुनः प्रयास करें।"
    
    # Handle specific error types
    if isinstance(error, PhoneNumberInvalidError):
        error_message = "The phone number format is invalid. Please enter a valid phone number with country code."
        error_message_hindi = "फोन नंबर प्रारूप अमान्य है। कृपया देश कोड के साथ एक मान्य फोन नंबर दर्ज करें।"
    
    elif isinstance(error, PhoneCodeInvalidError):
        error_message = "The verification code is invalid. Please check and try again."
        error_message_hindi = "सत्यापन कोड अमान्य है। कृपया जांचें और फिर से प्रयास करें।"
    
    elif isinstance(error, PhoneCodeExpiredError):
        error_message = "The verification code has expired. Please use /auth to request a new code."
        error_message_hindi = "सत्यापन कोड समाप्त हो गया है। कृपया नया कोड प्राप्त करने के लिए /auth का उपयोग करें।"
        
        # Reset user state in database
        if update and update.effective_user:
            user_id = update.effective_user.id
            if mongo_available:
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$unset": {"state": "", "phone": ""}}
                )
    
    elif isinstance(error, SessionPasswordNeededError):
        error_message = "Two-factor authentication is enabled. Please enter your password."
        error_message_hindi = "दो-चरणीय सत्यापन सक्षम है। कृपया अपना पासवर्ड दर्ज करें।"
        
        # Update user state to password verification
        if update and update.effective_user:
            user_id = update.effective_user.id
            if mongo_available:
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"state": "AWAITING_PASSWORD"}}
                )
    
    elif isinstance(error, PasswordHashInvalidError):
        error_message = "The password is incorrect. Please try again."
        error_message_hindi = "पासवर्ड गलत है। कृपया फिर से प्रयास करें।"
    
    elif isinstance(error, FloodWaitError):
        wait_time = getattr(error, 'seconds', 60)
        error_message = f"Too many requests. Please wait for {wait_time} seconds before trying again."
        error_message_hindi = f"बहुत अधिक अनुरोध। कृपया पुनः प्रयास करने से पहले {wait_time} सेकंड प्रतीक्षा करें।"
    
    # Send the error message if there's an update
    if update:
        try:
            if update.effective_message:
                await update.effective_message.reply_text(f"{error_message}\n\n{error_message_hindi}")
            elif update.callback_query:
                await update.callback_query.answer(f"{error_message}")
                await update.callback_query.message.reply_text(f"{error_message}\n\n{error_message_hindi}")
        except Exception as e:
            logger.error(f"Error sending error message: {e}")

async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE, source_text: str) -> bool:
    """Add a channel or group as a source for indexing."""
    user_id = update.effective_user.id
    
    # Check if user is authenticated by checking if the global client is authorized
    is_authorized = False
    try:
        if user_client and user_client.is_connected():
            is_authorized = await user_client.is_user_authorized()
        
        if not is_authorized:
            # Try to connect the client if it's not already
            await user_client.connect()
            is_authorized = await user_client.is_user_authorized()
    except Exception as e:
        logger.error(f"Error checking authorization: {e}")
    
    if not is_authorized:
        await update.message.reply_text(
            "You need to authenticate first. Use /auth to connect your Telegram account.\n\n"
            "आपको पहले प्रमाणित करने की आवश्यकता है। अपने टेलीग्राम खाते को कनेक्ट करने के लिए /auth का उपयोग करें।"
        )
        return False
        
    # Process source text - could be a username, invite link, or channel ID
    await update.message.reply_text(
        f"Adding {source_text} as a source... Please wait.\n\n"
        f"{source_text} को स्रोत के रूप में जोड़ रहा है... कृपया प्रतीक्षा करें।"
    )
    
    try:
        # Try to resolve the source and add it to the user's sources
        result = await fetch_channel_content(user_id, source_text)
        
        if result:
            await update.message.reply_text(
                f"Successfully added {source_text}. {result.get('count', 0)} messages indexed.\n\n"
                f"{source_text} सफलतापूर्वक जोड़ा गया। {result.get('count', 0)} संदेश अनुक्रमित।"
            )
            return True
        else:
            await update.message.reply_text(
                f"Failed to add {source_text}. Please check the source name/link and try again.\n"
                f"{source_text} को जोड़ने में विफल। कृपया स्रोत नाम/लिंक जांचें और पुनः प्रयास करें।"
            )
            return False
    except Exception as e:
        logger.error(f"Error adding source: {e}")
        await update.message.reply_text(
            f"Error: {str(e)}\n\n"
            f"त्रुटि: {str(e)}"
        )
        return False

# Function to clean up the session when authentication fails or times out
async def cleanup_session(user_id, context=None):
    global user_client
    try:
        logger.info(f"Starting cleanup for user {user_id}")
        
        # Disconnect client if it exists
        if user_client is not None:
            try:
                await user_client.disconnect()
                logger.info(f"Disconnected client for user {user_id}")
            except Exception as e:
                logger.error(f"Error disconnecting client: {e}")
        
        # Reset user state in context if available
        if context and context.user_data:
            context.user_data["state"] = None
            keys_to_keep = ["chat_data", "user_data", "bot_data"]
            for key in list(context.user_data.keys()):
                if key not in keys_to_keep:
                    try:
                        del context.user_data[key]
                    except KeyError:
                        pass
            logger.info(f"Reset context for user {user_id}")
        
        # Reset user state in database
        if mongo_available:
            try:
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"state": None, "last_cleanup": datetime.now().isoformat()},
                     "$unset": {"phone": "", "phone_code_hash": "", "session_path": "", 
                              "is_authenticated": "", "authenticated_at": ""}}
                )
                logger.info(f"Reset state in database for user {user_id}")
            except Exception as e:
                logger.error(f"Error updating database during cleanup: {e}")
        
        # Remove all session files for this user from all possible locations
        session_locations = ['sessions', 'clean_sessions', '.']
        session_patterns = [
            f"user_{user_id}",
            f"{user_id}",
            f"user_session_{user_id}",
            f"tg_session_{user_id}",
            f"anon_{user_id}"
        ]
        
        for location in session_locations:
            if os.path.exists(location):
                for filename in os.listdir(location):
                    file_path = os.path.join(location, filename)
                    if any(pattern in filename for pattern in session_patterns) or (filename.startswith('+') and user_id in filename):
                        try:
                            if os.path.isfile(file_path):
                                os.remove(file_path)
                                logger.info(f"Removed session file: {file_path}")
                        except Exception as e:
                            logger.error(f"Error removing file {file_path}: {e}")
        
        # Set global client to None
        user_client = None
        logger.info(f"Cleanup completed for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error in cleanup_session for user {user_id}: {e}")
        return False

def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("connect", connect_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("recent", recent_command))
    application.add_handler(CommandHandler("auth", auth_command))
    
    # Add callback query handler
    application.add_handler(CallbackQueryHandler(button_click))
    
    # Add message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Add error handler to handle exceptions
    application.add_error_handler(error_handler)
    
    # Simple approach to check authorization
    loop = asyncio.get_event_loop()
    
    # Connect the client
    loop.run_until_complete(user_client.connect())
    
    # Check if already authorized
    if not loop.run_until_complete(user_client.is_user_authorized()):
        logger.info("User not authorized, starting with bot token")
        user_client.start(bot_token=BOT_TOKEN)
    else:
        logger.info("User already authorized, using existing session")
    
    # Add event handler for new messages
    user_client.add_event_handler(process_new_message, events.NewMessage)
    
    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    logger.info("Bot started successfully!")

if __name__ == '__main__':
    main() 