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
from telethon.errors import ChannelPrivateError, ChatAdminRequiredError, PhoneNumberInvalidError, PhoneCodeInvalidError, SessionPasswordNeededError, PasswordHashInvalidError, PhoneCodeExpiredError, FloodWaitError
import pymongo
from fuzzywuzzy import fuzz
from telethon import events
import re
from enum import Enum

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
    try:
        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')  # Check if MongoDB is running
        db = client['telegram_search_bot']
        documents_collection = db['documents']
        users_collection = db['users']
        sources_collection = db['sources']
        logger.info("MongoDB connection successful")
    except Exception as e:
        logger.error(f"MongoDB connection error: {e}")
        mongo_available = False

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

# Telethon client for the bot
bot_client = TelegramClient('bot_session', API_ID, API_HASH)

# Dictionary to store user clients
user_clients = {}

# Constants for user state
AWAITING_SOURCE = "awaiting_source"
AWAITING_SEARCH = "awaiting_search"
AWAITING_PHONE = "awaiting_phone"
AWAITING_CODE = "awaiting_code"

class UserState(Enum):
    """Enumeration for user states in the authentication flow."""
    INITIAL = "initial"
    AWAITING_PHONE = "awaiting_phone"
    AWAITING_CODE = "awaiting_code"
    AWAITING_2FA = "awaiting_2fa"
    AUTHENTICATED = "authenticated"
    AWAITING_SEARCH = "awaiting_search"
    AWAITING_SOURCE = "awaiting_source"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when the command /start is issued."""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    # Check if user exists in database
    user_doc = users_collection.find_one({"user_id": user_id})
    
    if not user_doc:
        # New user - add to database
        users_collection.insert_one({
            "user_id": user_id,
            "username": update.effective_user.username,
            "first_name": user_name,
            "last_name": update.effective_user.last_name,
            "state": UserState.INITIAL.value,
            "created_at": datetime.now()
        })
        
        await update.message.reply_text(
            f"Welcome to Telegram Search Bot, {user_name}!\n\n"
            "This bot allows you to search for documents in your Telegram channels and groups.\n\n"
            "To get started, you need to:\n"
            "1. Authenticate with Telegram using /auth\n"
            "2. Add channels or groups to index using /add_source\n"
            "3. Search for documents using /search\n\n"
            "Type /help for more information about available commands.\n\n"
            f"नमस्ते {user_name}, टेलीग्राम सर्च बॉट में आपका स्वागत है!\n\n"
            "यह बॉट आपको अपने टेलीग्राम चैनलों और ग्रुप्स में दस्तावेज़ खोजने की सुविधा देता है।\n\n"
            "शुरू करने के लिए, आपको यह करना होगा:\n"
            "1. /auth का उपयोग करके टेलीग्राम के साथ प्रमाणित करें\n" 
            "2. /add_source का उपयोग करके इंडेक्स करने के लिए चैनल या ग्रुप जोड़ें\n"
            "3. /search का उपयोग करके दस्तावेज़ खोजें\n\n"
            "उपलब्ध कमांड्स के बारे में अधिक जानकारी के लिए /help टाइप करें।"
        )
    else:
        # Existing user
        user_state = user_doc.get("state", UserState.INITIAL.value)
        
        if user_state == UserState.AUTHENTICATED.value:
            await update.message.reply_text(
                f"Welcome back, {user_name}!\n\n"
                "You're already authenticated. You can:\n"
                "• Use /search to search for documents\n"
                "• Use /add_source to add more channels/groups\n"
                "• Use /recent to see recently indexed documents\n"
                "• Use /help for more information\n\n"
                f"वापस आने पर स्वागत है, {user_name}!\n\n"
                "आप पहले से ही प्रमाणित हैं। आप:\n"
                "• दस्तावेज़ खोजने के लिए /search का उपयोग कर सकते हैं\n"
                "• अधिक चैनल/ग्रुप जोड़ने के लिए /add_source का उपयोग कर सकते हैं\n"
                "• हाल ही में इंडेक्स किए गए दस्तावेज़ देखने के लिए /recent का उपयोग कर सकते हैं\n"
                "• अधिक जानकारी के लिए /help का उपयोग कर सकते हैं"
            )
        else:
            await update.message.reply_text(
                f"Welcome back, {user_name}!\n\n"
                "You need to complete the authentication process to use the bot.\n"
                "Use /auth to start or continue the authentication process.\n\n"
                f"वापस आने पर स्वागत है, {user_name}!\n\n"
                "बॉट का उपयोग करने के लिए आपको प्रमाणीकरण प्रक्रिया पूरी करने की आवश्यकता है।\n"
                "प्रमाणीकरण प्रक्रिया शुरू करने या जारी रखने के लिए /auth का उपयोग करें।"
            )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a help message when the command /help is issued."""
    await update.message.reply_text(
        "Telegram Search Bot - Help\n\n"
        "Available commands:\n\n"
        "• /start - Start the bot and get welcome message\n"
        "• /help - Show this help message\n"
        "• /auth - Authenticate with Telegram (required to use other features)\n"
        "• /add_source - Add a channel or group to be indexed\n"
        "• /search [query] - Search for documents (you can also type your query after /search)\n"
        "• /recent - Show recently indexed documents\n\n"
        
        "How to use the bot:\n"
        "1. First, authenticate using /auth and follow the instructions\n"
        "2. Add channels or groups you want to search in using /add_source\n"
        "3. Use /search followed by keywords to find documents\n\n"
        
        "Notes:\n"
        "• You must be a member of the channels/groups you want to add\n"
        "• The bot will only index documents (files, photos, videos, etc.)\n"
        "• Your authentication data is stored securely and only used to access your channels\n\n"
        
        "टेलीग्राम सर्च बॉट - मदद\n\n"
        "उपलब्ध कमांड्स:\n\n"
        "• /start - बॉट शुरू करें और स्वागत संदेश प्राप्त करें\n"
        "• /help - यह मदद संदेश दिखाएं\n"
        "• /auth - टेलीग्राम के साथ प्रमाणित करें (अन्य सुविधाओं का उपयोग करने के लिए आवश्यक)\n"
        "• /add_source - इंडेक्स करने के लिए चैनल या ग्रुप जोड़ें\n"
        "• /search [query] - दस्तावेज़ खोजें (आप /search के बाद अपनी क्वेरी भी टाइप कर सकते हैं)\n"
        "• /recent - हाल ही में इंडेक्स किए गए दस्तावेज़ दिखाएं\n\n"
        
        "बॉट का उपयोग कैसे करें:\n"
        "1. सबसे पहले, /auth का उपयोग करके प्रमाणित करें और निर्देशों का पालन करें\n"
        "2. जिन चैनलों या ग्रुप्स में आप खोजना चाहते हैं उन्हें /add_source का उपयोग करके जोड़ें\n"
        "3. दस्तावेज़ खोजने के लिए /search के बाद कीवर्ड का उपयोग करें\n\n"
        
        "नोट्स:\n"
        "• आपको उन चैनलों/ग्रुप्स का सदस्य होना चाहिए जिन्हें आप जोड़ना चाहते हैं\n"
        "• बॉट केवल दस्तावेज़ों (फ़ाइलें, फोटो, वीडियो, आदि) को इंडेक्स करेगा\n"
        "• आपका प्रमाणीकरण डेटा सुरक्षित रूप से संग्रहीत किया जाता है और केवल आपके चैनलों तक पहुंच के लिए उपयोग किया जाता है"
    )

async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start the authentication process."""
    user_id = update.effective_user.id
    
    # Check if user is already authenticated
    user_doc = users_collection.find_one({"user_id": user_id})
    
    if user_doc and user_doc.get("state") == UserState.AUTHENTICATED.value:
        await update.message.reply_text(
            "You are already authenticated! You can use /search to search for documents."
        )
        return
    
    # Add or update user in the database
    if not user_doc:
        # New user - insert into database
        users_collection.insert_one({
            "user_id": user_id,
            "username": update.effective_user.username,
            "first_name": update.effective_user.first_name,
            "last_name": update.effective_user.last_name,
            "state": UserState.AWAITING_PHONE.value,
            "created_at": datetime.now()
        })
    else:
        # Existing user - update state
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"state": UserState.AWAITING_PHONE.value}}
        )
    
    await update.message.reply_text(
        "Please enter your phone number in international format (e.g., +1234567890).\n\n"
        "This is required to access Telegram's API and search for documents in your channels."
    )

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
    """Search for documents by keyword."""
    user_id = update.effective_user.id
    
    # Check if user is authenticated
    user_doc = users_collection.find_one({"user_id": user_id})
    if not user_doc or user_doc.get("state") != UserState.AUTHENTICATED.value:
        await update.message.reply_text(
            "You need to authenticate first. Use /auth to start the process."
        )
        return
    
    # Get search query from command arguments
    query = " ".join(context.args) if context.args else ""
    
    if query:
        # If query is provided, search immediately
        await search_in_sources(update, context, query)
    else:
        # Otherwise, prompt user to enter a search query
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"state": UserState.AWAITING_SEARCH.value}}
        )
        
        await update.message.reply_text(
            "Please enter your search query:"
        )

def search_documents(query, user_id):
    """Search documents in MongoDB."""
    try:
        # Create text index if it doesn't exist
        try:
            documents_collection.create_index([("content", "text"), ("file_name", "text")])
        except Exception as e:
            logger.warning(f"Index creation warning: {str(e)}")
        
        # Build text search query
        search_query = {
            "$text": {"$search": query},
            "user_id": user_id  # Filter by the user_id to ensure privacy
        }
        
        # Set up projection to include score
        projection = {
            "score": {"$meta": "textScore"},
            "file_name": 1,
            "source": 1,
            "file_id": 1,
            "file_size": 1,
            "mime_type": 1,
            "created_at": 1
        }
        
        # Execute search with sorting by text score
        results = list(documents_collection.find(
            search_query,
            projection
        ).sort([("score", {"$meta": "textScore"})]).limit(50))
        
        logger.info(f"Search for '{query}' found {len(results)} documents")
        return results
    
    except Exception as e:
        logger.error(f"Error searching documents: {str(e)}")
        return []

async def search_in_sources(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None) -> None:
    """Search in user's sources for documents."""
    user_id = update.effective_user.id
    
    # Check if user is authenticated
    user_doc = users_collection.find_one({"user_id": user_id})
    if not user_doc or user_doc.get("state") != UserState.AUTHENTICATED.value:
        if user_doc and user_doc.get("state") == UserState.AWAITING_SEARCH.value:
            # User is in search state but not authenticated
            await update.message.reply_text("You need to authenticate first. Use /auth to start the process.")
            # Reset state
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"state": UserState.INITIAL.value}}
            )
        else:
            await update.message.reply_text("You need to authenticate first. Use /auth to start the process.")
        return
    
    # Get the search query
    if query is None:
        # If no direct query provided, check if it's from command arguments
        query = " ".join(context.args) if context.args else ""
    
    # Check if user is in AWAITING_SEARCH state
    if user_doc.get("state") == UserState.AWAITING_SEARCH.value and not query:
        # User is responding to a prompt for search query
        query = update.message.text.strip()
        
        # Reset user state back to AUTHENTICATED
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"state": UserState.AUTHENTICATED.value}}
        )
    
    if not query:
        await update.message.reply_text("Please provide a search query.")
        return
    
    # Send temporary message during search
    temp_message = await update.message.reply_text("Searching for documents... This may take a moment.")
    
    # Perform the search
    results = search_documents(query, user_id)
    
    if not results:
        await temp_message.edit_text(f"No documents found matching '{query}'.")
        return
    
    # Format the search results
    result_text = f"Found {len(results)} documents matching '{query}':\n\n"
    
    # Display first 10 results
    for i, doc in enumerate(results[:10], 1):
        file_name = doc.get("file_name", "Unknown")
        source = doc.get("source", "Unknown source")
        size = format_size(doc.get("file_size", 0))
        
        result_text += f"{i}. {file_name}\n"
        result_text += f"   Source: {source}\n"
        result_text += f"   Size: {size}\n\n"
    
    # Add note if there are more results
    if len(results) > 10:
        result_text += f"...and {len(results) - 10} more. Please refine your search for better results."
    
    # Edit the temporary message with the results
    await temp_message.edit_text(result_text)

def format_size(size_bytes):
    """Format file size from bytes to human readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

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
    """Handle user messages based on state."""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    # Get user from database
    user_doc = users_collection.find_one({"user_id": user_id})
    
    if not user_doc:
        # New user - welcome message
        await update.message.reply_text(
            "Welcome to Telegram Search Bot! Use /auth to start the authentication process."
        )
        return
    
    # Handle user based on current state
    user_state = user_doc.get("state", UserState.INITIAL.value)
    
    if user_state == UserState.AWAITING_PHONE.value:
        # User is entering phone number
        phone = message_text.strip()
        
        # Validate phone number format
        if not re.match(r'^\+[0-9]{7,15}$', phone):
            await update.message.reply_text(
                "Invalid phone number format. Please enter your phone number in international format (e.g., +1234567890)."
            )
            return
        
        try:
            # Create a new Telethon client for this user
            client = TelegramClient(
                f"sessions/{user_id}",
                API_ID,
                API_HASH,
                timeout=120  # Increase timeout to 2 minutes
            )
            
            await client.connect()
            
            # Start the authentication process
            # Use a longer timeout for code expiration (max 30 minutes)
            await client.send_code_request(phone, timeout=1800)
            
            # Update user state and save phone
            users_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "state": UserState.AWAITING_CODE.value,
                        "phone": phone,
                        "code_requested_at": datetime.now()  # Track when code was requested
                    }
                }
            )
            
            await update.message.reply_text(
                "A verification code has been sent to your Telegram account. "
                "Please enter the code you received.\n\n"
                "Note: This code will expire in 30 minutes."
            )
            
            await client.disconnect()
            
        except PhoneNumberInvalidError:
            await update.message.reply_text(
                "The phone number is invalid. Please enter a valid phone number in international format."
            )
            # Reset state
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"state": UserState.AWAITING_PHONE.value}}
            )
        except FloodWaitError as e:
            await update.message.reply_text(
                f"Too many attempts. Please try again after {e.seconds} seconds."
            )
            # Reset state
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"state": UserState.AWAITING_PHONE.value}}
            )
        except Exception as e:
            logger.error(f"Error sending code to {phone}: {str(e)}")
            await update.message.reply_text(
                "An error occurred while sending the verification code. Please try again later."
            )
            # Reset state
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"state": UserState.AWAITING_PHONE.value}}
            )
    
    elif user_state == UserState.AWAITING_CODE.value:
        # User is entering verification code
        code = message_text.strip()
        
        # Validate code format (should be 5 digits)
        if not re.match(r'^\d{5}$', code):
            await update.message.reply_text(
                "Invalid code format. The verification code should be 5 digits."
            )
            return
        
        phone = user_doc.get("phone")
        if not phone:
            await update.message.reply_text(
                "Phone number not found. Please start the authentication process again with /auth."
            )
            # Reset state
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"state": UserState.INITIAL.value}}
            )
            return
        
        # Check if code has expired (after 30 minutes)
        code_requested_at = user_doc.get("code_requested_at")
        if code_requested_at:
            code_requested_at = code_requested_at.replace(tzinfo=None)  # Remove timezone for comparison
            expiry_time = code_requested_at + timedelta(minutes=30)
            if datetime.now() > expiry_time:
                await update.message.reply_text(
                    "The verification code has expired. Please use /auth to request a new code."
                )
                # Reset state
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"state": UserState.INITIAL.value}}
                )
                return
        
        try:
            # Create a client for this user
            client = TelegramClient(
                f"sessions/{user_id}",
                API_ID,
                API_HASH,
                timeout=120  # Increase timeout to 2 minutes
            )
            
            await client.connect()
            
            # Try to sign in with the code
            await client.sign_in(phone, code)
            
            # If successful, update user state to authenticated
            users_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "state": UserState.AUTHENTICATED.value,
                        "authenticated_at": datetime.now()
                    }
                }
            )
            
            await update.message.reply_text(
                "Authentication successful! You can now use /search to search for documents in your channels and groups."
            )
            
            await client.disconnect()
            
        except PhoneCodeInvalidError:
            await update.message.reply_text(
                "The verification code is invalid. Please check and enter the correct code."
            )
        except PhoneCodeExpiredError:
            await update.message.reply_text(
                "The verification code has expired. Please use /auth to request a new code."
            )
            # Reset state to initial
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"state": UserState.INITIAL.value}}
            )
            
            await client.disconnect()
        except SessionPasswordNeededError:
            # 2FA is enabled, need password
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"state": UserState.AWAITING_2FA.value}}
            )
            
            await update.message.reply_text(
                "Two-factor authentication is enabled for your account. Please enter your password."
            )
            
            await client.disconnect()
            
        except Exception as e:
            logger.error(f"Error signing in with code for user {user_id}: {str(e)}")
            await update.message.reply_text(
                f"An error occurred during authentication: {str(e)}\n\nPlease try again with /auth."
            )
            # Reset state
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"state": UserState.INITIAL.value}}
            )
            
            try:
                await client.disconnect()
            except:
                pass
    
    elif user_state == UserState.AWAITING_2FA.value:
        # User is entering 2FA password
        password = message_text.strip()
        
        phone = user_doc.get("phone")
        if not phone:
            await update.message.reply_text(
                "Phone number not found. Please start the authentication process again with /auth."
            )
            # Reset state
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"state": UserState.INITIAL.value}}
            )
            return
        
        try:
            # Create a client for this user
            client = TelegramClient(
                f"sessions/{user_id}",
                API_ID,
                API_HASH
            )
            
            await client.connect()
            
            # Try to complete sign-in with password
            await client.sign_in(password=password)
            
            # If successful, update user state to authenticated
            users_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "state": UserState.AUTHENTICATED.value,
                        "authenticated_at": datetime.now()
                    }
                }
            )
            
            await update.message.reply_text(
                "Authentication successful! You can now use /search to search for documents in your channels and groups."
            )
            
            await client.disconnect()
            
        except PasswordHashInvalidError:
            await update.message.reply_text(
                "The password is incorrect. Please try again."
            )
        except Exception as e:
            logger.error(f"Error signing in with 2FA for user {user_id}: {str(e)}")
            await update.message.reply_text(
                f"An error occurred during 2FA authentication: {str(e)}\n\nPlease try again with /auth."
            )
            # Reset state
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"state": UserState.INITIAL.value}}
            )
            
            try:
                await client.disconnect()
            except:
                pass
    
    elif user_state == UserState.AUTHENTICATED.value:
        # User is authenticated, check if they're trying to search
        if message_text.startswith('/'):
            # This is a command, let the command handler handle it
            return
            
        # Assume user wants to search
        await search_in_sources(update, context, message_text)
    
    elif user_state == UserState.AWAITING_SEARCH.value:
        # User is entering a search query
        await search_in_sources(update, context)
    
    else:
        # Default response for unrecognized state
        await update.message.reply_text(
            "I'm not sure what you're trying to do. Use /help to see available commands."
        )

async def connect_to_source(update: Update, context: ContextTypes.DEFAULT_TYPE, source_text: str) -> None:
    """Connect to a channel or group."""
    user_id = update.effective_user.id
    user_info = users_collection.find_one({"user_id": user_id})
    
    # Check if user is authenticated
    if not user_info.get("authenticated", False):
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
        result = await fetch_channel_content(update, context, source_text)
        
        if result:
            await update.message.reply_text(
                f"Successfully connected to {source_text}. {result['count']} messages indexed.\n"
                f"{source_text} से सफलतापूर्वक जुड़ गए। {result['count']} संदेश अनुक्रमित।"
            )
        else:
            await update.message.reply_text(
                f"Failed to connect to {source_text}. Please check the source name/link and try again.\n"
                f"{source_text} से कनेक्ट करने में विफल। कृपया स्रोत नाम/लिंक जांचें और पुन: प्रयास करें।"
            )
    except Exception as e:
        logger.error(f"Error connecting to source: {e}")
        await update.message.reply_text(
            f"Error: {str(e)}\n"
            f"त्रुटि: {str(e)}"
        )

async def fetch_channel_content(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: str) -> None:
    """Fetch and index content from a Telegram channel or group."""
    global user_client
    
    user_id = update.effective_user.id
    
    # Check if user is authenticated
    user_doc = users_collection.find_one({"user_id": user_id})
    if not user_doc or user_doc.get("state") != UserState.AUTHENTICATED.value:
        await update.message.reply_text(
            "You need to authenticate first. Use /auth to start the process."
        )
        return
    
    # Send initial status message
    status_message = await update.message.reply_text(
        "Starting to fetch content from the channel/group. This may take a while depending on the amount of content..."
    )
    
    try:
        # Create a client for this user
        client = TelegramClient(
            f"sessions/{user_id}",
            API_ID,
            API_HASH
        )
        
        await client.connect()
        
        # Check if the client is authorized
        if not await client.is_user_authorized():
            await status_message.edit_text(
                "You are not properly authenticated. Please use /auth to authenticate again."
            )
            await client.disconnect()
            return
        
        # Try to validate the chat_id before proceeding
        try:
            # Try to get entity info to validate the chat
            entity = await client.get_entity(chat_id)
            source_name = getattr(entity, 'title', chat_id)
        except Exception as e:
            await status_message.edit_text(
                f"Failed to access the specified channel/group: {str(e)}\n\n"
                f"Make sure you provided a valid channel username, invite link, or ID, and that you have access to it."
            )
            await client.disconnect()
            return
        
        # Store the source in the database if it doesn't exist
        source_doc = sources_collection.find_one({
            "user_id": user_id,
            "source_id": str(entity.id)
        })
        
        if not source_doc:
            sources_collection.insert_one({
                "user_id": user_id,
                "source_id": str(entity.id),
                "source_name": source_name,
                "source_type": "channel" if hasattr(entity, "broadcast") else "group",
                "added_at": datetime.now(),
                "last_indexed": None
            })
        
        # Update status message
        await status_message.edit_text(
            f"Fetching documents from: {source_name}...\n"
            "This may take a while depending on the amount of content."
        )
        
        # Create a set to track already processed file hashes to avoid duplicates
        processed_hashes = set()
        
        # Get the last indexed message_id if any
        last_indexed_id = None
        if source_doc and source_doc.get("last_indexed_message_id"):
            last_indexed_id = source_doc.get("last_indexed_message_id")
        
        # Counter for new documents
        new_docs_count = 0
        last_message_id = None
        
        # Fetch messages from the channel/group
        async for message in client.iter_messages(entity, limit=1000, reverse=True if last_indexed_id else False):
            # Skip messages already indexed
            if last_indexed_id and message.id <= last_indexed_id:
                continue
            
            # Track last message ID for updating the source
            last_message_id = message.id
            
            # Check if message has a document/media
            if message.document or message.photo or message.video or message.audio:
                try:
                    # Get media attributes
                    media = message.document or message.photo or message.video or message.audio
                    
                    # Skip if no media or already processed
                    if not media:
                        continue
                    
                    # Extract file attributes
                    file_id = media.id
                    file_name = getattr(media, 'attributes', [{}])[0].file_name if hasattr(media, 'attributes') and hasattr(media.attributes[0], 'file_name') else f"file_{media.id}"
                    file_size = getattr(media, 'size', 0)
                    mime_type = getattr(media, 'mime_type', '')
                    
                    # For photos without file name
                    if message.photo and not file_name:
                        file_name = f"photo_{media.id}.jpg"
                    
                    # Calculate file hash for deduplication
                    file_hash = hashlib.md5(f"{file_id}_{file_size}_{file_name}".encode()).hexdigest()
                    
                    # Skip if already processed in this batch
                    if file_hash in processed_hashes:
                        continue
                    
                    processed_hashes.add(file_hash)
                    
                    # Check if document already exists in database
                    existing_doc = documents_collection.find_one({
                        "user_id": user_id,
                        "file_hash": file_hash
                    })
                    
                    if not existing_doc:
                        # Prepare document data
                        doc_data = {
                            "user_id": user_id,
                            "source_id": str(entity.id),
                            "source": source_name,
                            "message_id": message.id,
                            "file_id": str(file_id),
                            "file_name": file_name,
                            "file_size": file_size,
                            "mime_type": mime_type,
                            "file_hash": file_hash,
                            "content": message.text if message.text else "",
                            "caption": message.caption if message.caption else "",
                            "created_at": datetime.now()
                        }
                        
                        # Insert the document into the database
                        documents_collection.insert_one(doc_data)
                        new_docs_count += 1
                    
                except Exception as e:
                    logger.error(f"Error processing message {message.id}: {str(e)}")
            
            # Update status periodically
            if new_docs_count > 0 and new_docs_count % 10 == 0:
                await status_message.edit_text(
                    f"Fetching from {source_name}...\n"
                    f"Found {new_docs_count} new documents so far."
                )
        
        # Update the last indexed message ID in the source
        if last_message_id:
            sources_collection.update_one(
                {"user_id": user_id, "source_id": str(entity.id)},
                {
                    "$set": {
                        "last_indexed": datetime.now(),
                        "last_indexed_message_id": last_message_id
                    }
                }
            )
        
        # Final status update
        if new_docs_count > 0:
            await status_message.edit_text(
                f"Completed! Found and indexed {new_docs_count} new documents from {source_name}."
            )
        else:
            await status_message.edit_text(
                f"No new documents found in {source_name}."
            )
        
        await client.disconnect()
    
    except Exception as e:
        logger.error(f"Error fetching content from {chat_id}: {str(e)}")
        await status_message.edit_text(
            f"An error occurred while fetching content: {str(e)}"
        )
        try:
            await client.disconnect()
        except:
            pass

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

async def add_source_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a Telegram channel or group to be indexed."""
    user_id = update.effective_user.id
    
    # Check if user is authenticated
    user_doc = users_collection.find_one({"user_id": user_id})
    if not user_doc or user_doc.get("state") != UserState.AUTHENTICATED.value:
        await update.message.reply_text(
            "You need to authenticate first. Use /auth to start the process."
        )
        return
    
    # Check if source is provided as argument
    if not context.args:
        # Prompt user to enter source
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"state": UserState.AWAITING_SOURCE.value}}
        )
        
        await update.message.reply_text(
            "Please enter the username, ID, or invite link of the Telegram channel or group you want to add.\n\n"
            "For example:\n"
            "- @channelname\n"
            "- https://t.me/channelname\n"
            "- https://t.me/+abcdefghijk (invite link)"
        )
        return
    
    # Get source from arguments
    source_text = " ".join(context.args)
    
    # Call fetch_channel_content to add the source and index its content
    await fetch_channel_content(update, context, source_text)

async def handle_add_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the source input when user is in AWAITING_SOURCE state."""
    user_id = update.effective_user.id
    source_text = update.message.text.strip()
    
    # Reset user state
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"state": UserState.AUTHENTICATED.value}}
    )
    
    # Call fetch_channel_content to add the source and index its content
    await fetch_channel_content(update, context, source_text)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the telegram bot."""
    try:
        if update:
            # Log the error before we do anything else
            logger.error(f"Exception while handling an update: {context.error} with update {update}")
            
            # Send a message to the user
            error_message = "Sorry, an error occurred while processing your request."
            
            # Add hindi translation
            error_message_hindi = "क्षमा करें, आपके अनुरोध को संसाधित करते समय एक त्रुटि हुई।"
            
            # Handle different types of errors
            if isinstance(context.error, PhoneNumberInvalidError):
                error_message = "The phone number format is invalid. Please use the international format with country code."
                error_message_hindi = "फोन नंबर प्रारूप अमान्य है। कृपया देश कोड के साथ अंतरराष्ट्रीय प्रारूप का उपयोग करें।"
            elif isinstance(context.error, PhoneCodeInvalidError):
                error_message = "The verification code is invalid. Please check and try again."
                error_message_hindi = "सत्यापन कोड अमान्य है। कृपया जांचें और पुनः प्रयास करें।"
            elif isinstance(context.error, PhoneCodeExpiredError):
                error_message = "The verification code has expired. Please use /auth to request a new code."
                error_message_hindi = "सत्यापन कोड समाप्त हो गया है। कृपया नया कोड प्राप्त करने के लिए /auth का उपयोग करें।"
            elif isinstance(context.error, SessionPasswordNeededError):
                error_message = "Two-factor authentication is enabled. Please enter your password."
                error_message_hindi = "दो-चरणीय प्रमाणीकरण सक्षम है। कृपया अपना पासवर्ड दर्ज करें।"
            
            # Send the error message
            if update.effective_message:
                await update.effective_message.reply_text(
                    f"{error_message}\n\n{error_message_hindi}"
                )
            elif update.callback_query:
                await update.callback_query.message.reply_text(
                    f"{error_message}\n\n{error_message_hindi}"
                )
        else:
            logger.error(f"Exception while handling an update: {context.error}")
    except Exception as e:
        logger.error(f"Error in error handler: {e}")
        logger.error(f"Original error: {context.error}")

def main() -> None:
    """Start the bot."""
    # Initialize database collections if not exists
    if "users" not in db.list_collection_names():
        db.create_collection("users")
    
    if "documents" not in db.list_collection_names():
        db.create_collection("documents")
        # Create text index for searching
        db.documents.create_index([("content", "text"), ("file_name", "text")])
    
    if "sources" not in db.list_collection_names():
        db.create_collection("sources")
    
    # Create sessions directory if it doesn't exist
    os.makedirs("sessions", exist_ok=True)
    
    # Create the Application instance
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("recent", recent_command))
    application.add_handler(CommandHandler("auth", auth_command))
    application.add_handler(CommandHandler("add_source", add_source_command))
    
    # Add callback query handler for inline buttons
    application.add_handler(CallbackQueryHandler(button_click))
    
    # Add message handler to process regular messages based on user state
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_message
    ))
    
    # Special handler for AWAITING_SOURCE state
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_add_source,
        # Only handle messages when user is in AWAITING_SOURCE state
        lambda update: users_collection.find_one({"user_id": update.effective_user.id, "state": UserState.AWAITING_SOURCE.value}) is not None
    ))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    logger.info("Bot started successfully!")

if __name__ == '__main__':
    main() 