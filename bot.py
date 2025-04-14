import os
import hashlib
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode
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
import html
from telegram.error import BadRequest
from telethon import types
import uuid
from bson import ObjectId

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

# Use the existing session file directly - exactly like the working auth_simple.py approach
SESSION_PHONE = os.getenv('Phone_number', '')  # Use the phone number directly
user_client = TelegramClient(
    SESSION_PHONE,  # Phone number as session name
    API_ID,
    API_HASH
)


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
        "/sources - List all connected sources\n"
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
        "/sources - सभी जुड़े स्रोतों की सूची देखें\n"
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
    """Prompt the user to enter a search query."""
    await update.message.reply_text(
        "Please enter what you would like to search for.\n\n"
        "कृपया बताएं कि आप क्या खोजना चाहते हैं।"
    )
    context.user_data['state'] = AWAITING_SEARCH

async def recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show recent documents."""
    user_id = update.effective_user.id
    
    if not mongo_available:
        await update.message.reply_text(
            "Sorry, this functionality requires MongoDB which is not currently available.\n"
            "Please install and start MongoDB to enable full functionality.\n\n"
            "क्षमा करें, इस कार्यक्षमता के लिए MongoDB की आवश्यकता है जो वर्तमान में उपलब्ध नहीं है।\n"
            "पूर्ण कार्यक्षमता सक्षम करने के लिए कृपया MongoDB इंस्टॉल करें और शुरू करें।"
        )
        return
    
    # Show loading message
    progress_message = await update.message.reply_text(
        "Fetching recent documents... Please wait.\n\n"
        "हाल के दस्तावेज़ लाए जा रहे हैं... कृपया प्रतीक्षा करें।"
    )
    
    # Get recent documents
    recent_docs = documents_collection.find(
        {'user_id': user_id}
    ).sort('date', -1).limit(50)  # Get the latest 50 documents
    
    recent_docs_list = list(recent_docs)
    if not recent_docs_list:
        await progress_message.edit_text(
            "No documents found. Try connecting to a channel or group first.\n\n"
            "कोई दस्तावेज़ नहीं मिला। पहले किसी चैनल या ग्रुप से कनेक्ट करने का प्रयास करें।"
        )
        return
    
    # Save results in user context for pagination
    context.user_data["search_results"] = recent_docs_list
    context.user_data["search_query"] = "recent documents"
    context.user_data["page"] = 0
    
    # Format results message using the same formatter as search
    result_message = format_search_results(recent_docs_list, "recent documents", 0)
    
    # Create a keyboard for pagination or actions
    keyboard = []
    buttons_per_row = 3
    
    # Add buttons for each result in the current page
    current_row = []
    for i, doc in enumerate(recent_docs_list[:10]):  # Show 10 results per page
        button_text = f"{i+1}"
        callback_data = f"view_{doc['_id']}"
        current_row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
        
        # Create a new row after buttons_per_row buttons
        if len(current_row) == buttons_per_row:
            keyboard.append(current_row)
            current_row = []
    
    # Add any remaining buttons
    if current_row:
        keyboard.append(current_row)
    
    # Add navigation buttons if needed
    if len(recent_docs_list) > 10:
        keyboard.append([
            InlineKeyboardButton("◀️ Previous", callback_data="prev"),
            InlineKeyboardButton("Next ▶️", callback_data="next")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Try to send the message with the buttons
    try:
        await progress_message.edit_text(result_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    except BadRequest as e:
        # If there's an HTML parsing error, send the message without HTML formatting
        if "can't parse entities" in str(e).lower():
            await progress_message.edit_text(
                f"Found {len(recent_docs_list)} recent documents. Click a number to view details.\n\n"
                f"{len(recent_docs_list)} हाल के दस्तावेज़ मिले। विवरण देखने के लिए एक नंबर पर क्लिक करें।",
                reply_markup=reply_markup
            )
        else:
            raise

async def search_in_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search for documents based on a query from the user."""
    user_id = update.effective_user.id
    
    # Check if MongoDB is available
    if not mongo_available:
        await update.message.reply_text(
            "MongoDB is not available. Please try again later.\n\n"
            "MongoDB उपलब्ध नहीं है। कृपया बाद में पुनः प्रयास करें।"
        )
        return
    
    # Log the search query
    query = context.args[0] if context.args else ""
    for arg in context.args[1:]:
        query += f" {arg}"
    
    logger.info(f"User {user_id} searching for: {query}")
    
    # If this was called from handle_message, use the message text as query
    if not query and hasattr(update, "message") and update.message.text:
        query = update.message.text
    
    # Check if query is empty
    if not query:
        await update.message.reply_text(
            "Please provide a search query after the /search command. For example: /search document name\n\n"
            "/search कमांड के बाद एक खोज क्वेरी प्रदान करें। उदाहरण के लिए: /search document name"
        )
        return
    
    # Notify user that search is in progress
    progress_message = await update.message.reply_text(
        f"Searching for: {query}... Please wait.\n\n"
        f"खोज रहा है: {query}... कृपया प्रतीक्षा करें।"
    )
    
    try:
        # Create regex pattern for case-insensitive search
        regex_pattern = {"$regex": query, "$options": "i"}
        
        # Find documents that match the query
        results = list(documents_collection.find({
            "user_id": user_id,
            "$or": [
                {"text": regex_pattern},
                {"content_searchable": regex_pattern},
                {"file_name": regex_pattern}
            ]
        }).sort("date", pymongo.DESCENDING).limit(50))  # Get latest 50 results
        
        # Check if no results found
        if not results:
            await progress_message.edit_text(
                f"No results found for '{query}'.\n\n"
                f"'{query}' के लिए कोई परिणाम नहीं मिला।"
            )
            return
        
        # Save results in user context for pagination
        context.user_data["search_results"] = results
        context.user_data["search_query"] = query
        context.user_data["page"] = 0
        
        # Format results message
        result_message = format_search_results(results, query, 0)
        
        # Create a keyboard for pagination or actions
        keyboard = []
        buttons_per_row = 3
        
        # Add buttons for each result in the current page
        current_row = []
        for i, doc in enumerate(results[:10]):  # Show 10 results per page
            button_text = f"{i+1}"
            callback_data = f"view_{doc['_id']}"
            current_row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
            
            # Create a new row after buttons_per_row buttons
            if len(current_row) == buttons_per_row:
                keyboard.append(current_row)
                current_row = []
        
        # Add any remaining buttons
        if current_row:
            keyboard.append(current_row)
        
        # Add navigation buttons if needed
        if len(results) > 10:
            keyboard.append([
                InlineKeyboardButton("◀️ Previous", callback_data="prev"),
                InlineKeyboardButton("Next ▶️", callback_data="next")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Try to send the message with the buttons
        try:
            await progress_message.edit_text(result_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except BadRequest as e:
            # If there's an HTML parsing error, send the message without HTML formatting
            if "can't parse entities" in str(e).lower():
                await progress_message.edit_text(
                    f"Found {len(results)} results for '{query}'. Click a number to view details.\n\n"
                    f"'{query}' के लिए {len(results)} परिणाम मिले। विवरण देखने के लिए एक नंबर पर क्लिक करें।",
                    reply_markup=reply_markup
                )
            else:
                raise
    
    except Exception as e:
        logger.error(f"Search error: {e}")
        await progress_message.edit_text(
            f"Error searching: {str(e)}\n\n"
            f"खोज में त्रुटि: {str(e)}"
        )

def format_search_results(results, query, page=0):
    """Format search results for display"""
    start_idx = page * 10
    end_idx = min(start_idx + 10, len(results))
    
    # Create the header
    message = f"<b>Found {len(results)} results for '{query}'</b>\n\n"
    
    # Add each result with its number
    for i, doc in enumerate(results[start_idx:end_idx], start=start_idx+1):
        # Get file type and icon
        file_type = doc.get("file_type", "")
        icon = get_file_icon(file_type)
        
        # Format the date
        date_str = doc["date"].strftime("%d %b %Y") if "date" in doc else "Unknown date"
        
        # Get source name
        source_name = doc.get("source_name", "Unknown source")
        
        # Format the message
        message += f"{i}. {icon} "
        
        # Add filename if available
        if doc.get("file_name"):
            message += f"<b>{doc['file_name']}</b> - "
        
        # Add text snippet (limited to 50 chars)
        text = doc.get("text", "")
        if text:
            if len(text) > 50:
                text = text[:47] + "..."
            message += f"{text}\n"
        else:
            message += f"[No text]\n"
        
        # Add metadata
        message += f"   <i>From {source_name} - {date_str}</i>\n\n"
    
    # Add pagination info if needed
    if len(results) > 10:
        message += f"Showing results {start_idx+1}-{end_idx} of {len(results)}\n"
    
    message += "\nClick a number to view file details and download options."
    
    return message

def get_file_icon(file_type):
    """Return an appropriate icon for the file type"""
    if not file_type:
        return "📄"
    
    file_type = file_type.lower()
    if file_type in ["jpg", "jpeg", "png", "gif", "image"]:
        return "🖼️"
    elif file_type in ["mp4", "avi", "mov", "mkv", "video"]:
        return "🎬"
    elif file_type in ["mp3", "wav", "ogg", "audio"]:
        return "🔊"
    elif file_type == "pdf":
        return "📕"
    elif file_type in ["doc", "docx"]:
        return "📝"
    elif file_type in ["xls", "xlsx"]:
        return "📊"
    elif file_type in ["ppt", "pptx"]:
        return "📑"
    elif file_type in ["zip", "rar", "7z"]:
        return "🗜️"
    else:
        return "📄"

async def view_file(update: Update, context: ContextTypes.DEFAULT_TYPE, doc_id):
    """View file details and provide download option"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Check if MongoDB is available
    if not mongo_available:
        await query.answer("MongoDB is not available")
        await query.edit_message_text(
            "MongoDB is not available. Please try again later.\n\n"
            "MongoDB उपलब्ध नहीं है। कृपया बाद में पुनः प्रयास करें।"
        )
        return
    
    # Try to find the document
    try:
        # Convert ObjectID if it's a string
        if isinstance(doc_id, str):
            try:
                doc_id = ObjectId(doc_id)
            except Exception as e:
                logger.error(f"Error converting document ID {doc_id} to ObjectId: {e}")
                await query.answer("Error: Invalid document ID format")
                return
        
        # Get the document
        doc = documents_collection.find_one({"_id": doc_id, "user_id": user_id})
        
        if not doc:
            logger.error(f"Document not found: {doc_id} for user {user_id}")
            await query.answer("Document not found or access denied.")
            return
        
        # Format file details
        file_name = doc.get('file_name', 'Unnamed file')
        file_type = doc.get('file_type', 'unknown')
        file_size = doc.get('file_size', 0)
        date = doc.get('date', datetime.now())
        text = doc.get('text', '')
        source_name = doc.get('source_name', 'Unknown source')
        
        # Format file size
        if file_size:
            if file_size < 1024:
                size_text = f"{file_size} B"
            elif file_size < 1024 * 1024:
                size_text = f"{file_size/1024:.1f} KB"
            else:
                size_text = f"{file_size/(1024*1024):.1f} MB"
        else:
            size_text = "Unknown size"
        
        # Format the details message
        message_text = f"<b>📄 {file_name}</b>\n\n"
        
        if file_type:
            message_text += f"<b>Type:</b> {file_type.upper()}\n"
        
        message_text += f"<b>Size:</b> {size_text}\n"
        message_text += f"<b>Date:</b> {date.strftime('%Y-%m-%d %H:%M')}\n"
        message_text += f"<b>Source:</b> {source_name}\n\n"
        
        if text:
            message_text += f"<b>Content:</b>\n<i>{text}</i>\n\n"
        
        # Create keyboard with download button and back button
        keyboard = [
            [InlineKeyboardButton("⬇️ Download File", callback_data=f"download_{doc_id}")],
            [InlineKeyboardButton("🔙 Back to Results", callback_data="back_results")],
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except BadRequest as e:
            # If HTML parsing fails, send without HTML
            logger.error(f"Failed to send message with HTML: {e}")
            message_text = f"File: {file_name}\n\n"
            message_text += f"Type: {file_type.upper() if file_type else 'Unknown'}\n"
            message_text += f"Size: {size_text}\n"
            message_text += f"Date: {date.strftime('%Y-%m-%d %H:%M')}\n"
            message_text += f"Source: {source_name}\n\n"
            
            if text:
                message_text += f"Content:\n{text}\n\n"
                
            await query.edit_message_text(
                message_text,
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Error viewing file: {e}")
        await query.answer(f"Error: {str(e)}")

async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE, doc_id: str) -> None:
    """Download and send the file to the user."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Check if MongoDB is available
    if not mongo_available:
        await query.answer("MongoDB is not available. Please try again later.")
        return
    
    try:
        # Convert ObjectID if it's a string
        if isinstance(doc_id, str):
            try:
                doc_id = ObjectId(doc_id)
            except Exception as e:
                logger.error(f"Error converting document ID {doc_id} to ObjectId: {e}")
                await query.answer("Error: Invalid document ID format")
                return
        
        # Get document from MongoDB
        document = documents_collection.find_one({
            "_id": doc_id,
            "user_id": user_id
        })
        
        if not document:
            logger.error(f"Document not found: {doc_id} for user {user_id}")
            await query.answer("Document not found or access denied.")
            return
        
        # Check if user_client is connected and authorized
        if not user_client or not user_client.is_connected():
            await query.answer("Not connected to Telegram. Please authenticate first with /auth.")
            return
        
        if not await user_client.is_user_authorized():
            await query.answer("Not authorized. Please authenticate first with /auth.")
            return
        
        # Send a processing message
        await query.answer("Downloading file... Please wait.")
        
        # Get original message details
        original_message = document.get('original_message', {})
        chat_id = original_message.get('chat_id')
        message_id = original_message.get('message_id')
        
        if not chat_id or not message_id:
            await query.message.reply_text(
                "Error: Could not find original message details. Please try again.\n\n"
                "त्रुटि: मूल संदेश विवरण नहीं मिल सका। कृपया पुनः प्रयास करें।"
            )
            return
        
        # Get the message from Telegram
        message = await user_client.get_messages(chat_id, ids=message_id)
        
        if not message:
            await query.message.reply_text(
                "Error: Could not retrieve the message from Telegram. The message may have been deleted.\n\n"
                "त्रुटि: टेलीग्राम से संदेश प्राप्त नहीं किया जा सका। संदेश हटा दिया गया हो सकता है।"
            )
            return
        
        # Check if message has media
        if not message.media:
            await query.message.reply_text(
                "This message does not contain any file to download.\n\n"
                "इस संदेश में डाउनलोड करने के लिए कोई फ़ाइल नहीं है।"
            )
            return
        
        # Download the file
        file_path = await user_client.download_media(message, file="downloads/")
        
        if not file_path:
            await query.message.reply_text(
                "Error: Failed to download the file. Please try again.\n\n"
                "त्रुटि: फ़ाइल डाउनलोड करने में विफल। कृपया पुनः प्रयास करें।"
            )
            return
        
        # Send the file to the user
        file_name = os.path.basename(file_path)
        mime_type = document.get('mime_type', '')
        
        # Send status message
        status_message = await query.message.reply_text(
            f"File downloaded. Sending to you now...\n\n"
            f"फ़ाइल डाउनलोड की गई। अब आपको भेज रहे हैं..."
        )
        
        # Send based on the file type
        with open(file_path, 'rb') as file:
            if mime_type and mime_type.startswith('image/'):
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=file,
                    caption=f"File: {file_name}"
                )
            elif mime_type and mime_type.startswith('video/'):
                await context.bot.send_video(
                    chat_id=user_id,
                    video=file,
                    caption=f"File: {file_name}"
                )
            elif mime_type and mime_type.startswith('audio/'):
                await context.bot.send_audio(
                    chat_id=user_id,
                    audio=file,
                    caption=f"File: {file_name}"
                )
            else:
                # Send as document for all other types
                await context.bot.send_document(
                    chat_id=user_id,
                    document=file,
                    filename=file_name,
                    caption=f"File: {file_name}"
                )
        
        # Update status message
        await status_message.edit_text(
            f"✅ File sent successfully: {file_name}\n\n"
            f"✅ फ़ाइल सफलतापूर्वक भेजी गई: {file_name}"
        )
        
        # Clean up the file
        try:
            os.remove(file_path)
            logger.info(f"Deleted temporary file: {file_path}")
        except Exception as e:
            logger.error(f"Error deleting temporary file {file_path}: {e}")
            
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        await query.message.reply_text(
            f"Error downloading file: {str(e)}\n\n"
            f"फ़ाइल डाउनलोड करने में त्रुटि: {str(e)}"
        )

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button clicks from inline keyboards."""
    query = update.callback_query
    
    # Get the callback data
    data = query.data
    
    try:
        # Handle different callback types
        if data.startswith('view_'):
            # View file details
            doc_id = data.split('_', 1)[1]  # Split only on first _ to handle IDs with underscores
            try:
                await view_file(update, context, doc_id)
            except Exception as e:
                logger.error(f"Error in view_file: {e}")
                await query.answer(f"Error viewing file: {str(e)}")
        
        elif data.startswith('download_'):
            # Download file
            doc_id = data.split('_', 1)[1]  # Split only on first _ to handle IDs with underscores
            try:
                await download_file(update, context, doc_id)
            except Exception as e:
                logger.error(f"Error in download_file: {e}")
                await query.answer(f"Error downloading file: {str(e)}")
        
        elif data.startswith('reindex_'):
            # Reindex messages from an existing source
            source_id = data.split('_', 1)[1]  # Split only on first _ to handle IDs with underscores
            await reindex_source(update, context, source_id)
            
        elif data == "cancel_reindex":
            await query.edit_message_text(
                "Reindexing cancelled. No changes were made.\n\n"
                "फिर से इंडेक्सिंग रद्द की गई। कोई बदलाव नहीं किया गया।"
            )
            
        elif data == "connect":
            await connect_command(update, context)
            
        elif data == "search":
            await search_command(update, context)
            
        elif data == "recent":
            await recent_command(update, context)
            
        elif data == "auth_user":
            await auth_command(update, context)
        
        elif data == "back_results":
            # Return to search results
            if "search_results" in context.user_data and "search_query" in context.user_data:
                results = context.user_data["search_results"]
                query_text = context.user_data["search_query"]
                page = context.user_data.get("page", 0)
                
                # Format results message
                result_message = format_search_results(results, query_text, page)
                
                # Create a keyboard for pagination or actions
                keyboard = []
                buttons_per_row = 3
                
                # Add buttons for each result in the current page
                start_idx = page * 10
                end_idx = min(start_idx + 10, len(results))
                current_row = []
                
                for i in range(start_idx, end_idx):
                    idx = i - start_idx + 1
                    button_text = f"{i+1}"
                    callback_data = f"view_{results[i]['_id']}"
                    current_row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
                    
                    # Create a new row after buttons_per_row buttons
                    if len(current_row) == buttons_per_row:
                        keyboard.append(current_row)
                        current_row = []
                
                # Add any remaining buttons
                if current_row:
                    keyboard.append(current_row)
                
                # Add navigation buttons if needed
                nav_buttons = []
                if page > 0:
                    nav_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data="prev"))
                if (page + 1) * 10 < len(results):
                    nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data="next"))
                
                if nav_buttons:
                    keyboard.append(nav_buttons)
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Try to send the message with the buttons
                try:
                    await query.edit_message_text(result_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
                except BadRequest as e:
                    # If there's an HTML parsing error, send the message without HTML formatting
                    if "can't parse entities" in str(e).lower():
                        await query.edit_message_text(
                            f"Found {len(results)} results for '{query_text}'. Click a number to view details.\n\n"
                            f"'{query_text}' के लिए {len(results)} परिणाम मिले। विवरण देखने के लिए एक नंबर पर क्लिक करें।",
                            reply_markup=reply_markup
                        )
                    else:
                        raise
            else:
                await query.edit_message_text(
                    "Your search results are no longer available. Please try searching again.\n\n"
                    "आपके खोज परिणाम अब उपलब्ध नहीं हैं। कृपया फिर से खोजने का प्रयास करें।"
                )
        
        elif data == "prev" or data == "next":
            # Handle pagination
            if "search_results" in context.user_data and "search_query" in context.user_data:
                results = context.user_data["search_results"]
                query_text = context.user_data["search_query"]
                current_page = context.user_data.get("page", 0)
                
                # Calculate new page
                if data == "next":
                    new_page = current_page + 1
                else:  # prev
                    new_page = max(0, current_page - 1)
                
                # Update current page
                context.user_data["page"] = new_page
                
                # Format results message for the new page
                result_message = format_search_results(results, query_text, new_page)
                
                # Create a keyboard for pagination or actions
                keyboard = []
                buttons_per_row = 3
                
                # Add buttons for each result in the current page
                start_idx = new_page * 10
                end_idx = min(start_idx + 10, len(results))
                current_row = []
                
                for i in range(start_idx, end_idx):
                    button_text = f"{i+1}"
                    callback_data = f"view_{results[i]['_id']}"
                    current_row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
                    
                    # Create a new row after buttons_per_row buttons
                    if len(current_row) == buttons_per_row:
                        keyboard.append(current_row)
                        current_row = []
                
                # Add any remaining buttons
                if current_row:
                    keyboard.append(current_row)
                
                # Add navigation buttons if needed
                nav_buttons = []
                if new_page > 0:
                    nav_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data="prev"))
                if (new_page + 1) * 10 < len(results):
                    nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data="next"))
                
                if nav_buttons:
                    keyboard.append(nav_buttons)
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Try to send the message with the buttons
                try:
                    await query.edit_message_text(result_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
                except BadRequest as e:
                    # If there's an HTML parsing error, send the message without HTML formatting
                    if "can't parse entities" in str(e).lower():
                        await query.edit_message_text(
                            f"Found {len(results)} results (page {new_page+1}). Click a number to view details.\n\n"
                            f"{len(results)} परिणाम मिले (पेज {new_page+1})। विवरण देखने के लिए एक नंबर पर क्लिक करें।",
                            reply_markup=reply_markup
                        )
                    else:
                        raise
            else:
                await query.edit_message_text(
                    "Your search results are no longer available. Please try searching again.\n\n"
                    "आपके खोज परिणाम अब उपलब्ध नहीं हैं। कृपया फिर से खोजने का प्रयास करें।"
                )
        
        await query.answer()
        
    except Exception as e:
        logger.error(f"Button click error: {e}")
        await query.answer(f"Error: {str(e)}")

async def cleanup_downloads(max_age_hours=24):
    """Clean up old downloaded files to free up space.
    
    Args:
        max_age_hours: Maximum age of files in hours before they're deleted
    """
    try:
        downloads_dir = "downloads"
        if not os.path.exists(downloads_dir):
            return
            
        current_time = datetime.now()
        deleted_count = 0
        
        for filename in os.listdir(downloads_dir):
            file_path = os.path.join(downloads_dir, filename)
            
            # Skip directories
            if not os.path.isfile(file_path):
                continue
                
            # Get file age
            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            file_age = current_time - file_mtime
            
            # Delete files older than max_age_hours
            if file_age.total_seconds() > max_age_hours * 3600:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                    logger.info(f"Deleted old file: {file_path}")
                except Exception as e:
                    logger.error(f"Error deleting file {file_path}: {e}")
        
        if deleted_count > 0:
            logger.info(f"Cleanup: deleted {deleted_count} old files from downloads directory")
        
    except Exception as e:
        logger.error(f"Error during downloads cleanup: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle messages based on user state."""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    # Get user state from context
    user_state = context.user_data.get('state', None)
    
    logger.info(f"Handle message from user {user_id} in state: {user_state}")
    
    if user_state == AWAITING_SOURCE:
        # User has sent a channel/group name to connect to
        source_input = message_text.strip()
        
        # Process the source input (username or link)
        if source_input.startswith('@'):
            source_name = source_input[1:]  # Remove '@' prefix
        elif source_input.startswith('https://t.me/'):
            source_name = source_input.split('/')[-1]  # Get username from link
        elif source_input.startswith('t.me/'):
            source_name = source_input.split('/')[-1]
        else:
            source_name = source_input
        
        # Validate source name
        if not source_name:
            await update.message.reply_text(
                "Invalid channel or group name. Please send a valid username (e.g. @example) or link (e.g. https://t.me/example)."
            )
            return
        
        # Save the source in the database
        if mongo_available:
            try:
                # Check if source already exists for this user
                existing_source = sources_collection.find_one({
                    'user_id': user_id,
                    'source_name': source_name
                })
                
                if existing_source:
                    # Instead of just saying "already connected", offer to reindex
                    keyboard = [
                        [InlineKeyboardButton("Reindex Messages", callback_data=f"reindex_{existing_source['_id']}")],
                        [InlineKeyboardButton("Cancel", callback_data="cancel_reindex")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        f"You are already connected to {source_name}.\n"
                        f"Would you like to reindex messages from this source? This might help if messages weren't indexed before.\n\n"
                        f"आप पहले से ही {source_name} से जुड़े हुए हैं।\n"
                        f"क्या आप इस स्रोत से संदेशों को फिर से इंडेक्स करना चाहेंगे? यदि संदेश पहले इंडेक्स नहीं किए गए थे तो यह मदद कर सकता है।",
                        reply_markup=reply_markup
                    )
                    # Reset state since we're now waiting for button click
                    context.user_data['state'] = None
                else:
                    # Add new source
                    source_id = sources_collection.insert_one({
                        'user_id': user_id,
                        'source_name': source_name,
                        'date_added': datetime.now()
                    }).inserted_id
                    
                    connecting_message = await update.message.reply_text(
                        f"Successfully connected to {source_name}!\n"
                        f"Fetching existing messages and indexing them... This may take a while.\n\n"
                        f"{source_name} से सफलतापूर्वक जुड़ गए!\n"
                        f"मौजूदा संदेशों को फ़ेच और इंडेक्स किया जा रहा है... इसमें कुछ समय लग सकता है।"
                    )
                    
                    # Fetch and index existing messages
                    indexed_count = await fetch_and_index_messages(user_id, source_name, source_id)
                    
                    await connecting_message.edit_text(
                        f"Successfully connected to {source_name}!\n"
                        f"Indexed {indexed_count} messages from this source.\n\n"
                        f"{source_name} से सफलतापूर्वक जुड़ गए!\n"
                        f"इस स्रोत से {indexed_count} संदेशों को इंडेक्स किया गया।"
                    )
                    
                    # Reset user state
                    context.user_data['state'] = None
            except Exception as e:
                logger.error(f"Error connecting to source: {e}")
                await update.message.reply_text(
                    f"Error connecting to source: {str(e)}\n\n"
                    f"स्रोत से कनेक्ट करने में त्रुटि: {str(e)}"
                )
        else:
            await update.message.reply_text(
                "Sorry, MongoDB is not available. Cannot save source information.\n\n"
                "क्षमा करें, MongoDB उपलब्ध नहीं है। स्रोत जानकारी सहेज नहीं सकता।"
            )
    
    elif user_state == AWAITING_SEARCH:
        # User has sent a search query
        await search_in_sources(update, context)
        # Reset user state
        context.user_data['state'] = None
    
    elif user_state == AWAITING_PHONE:
        # Process phone number (handled by auth_command)
        pass
    
    elif user_state == AWAITING_CODE:
        # Process verification code (handled by auth_command)
        pass
    
    elif user_state == AWAITING_2FA:
        # Process 2FA password (handled by auth_command)
        pass
    
    else:
        # Default response for users not in any specific state
        await update.message.reply_text(
            "I'm not sure what you want to do. Try using one of these commands:\n"
            "/start - Start the bot\n"
            "/connect - Connect to a channel or group\n"
            "/search - Search for documents\n"
            "/recent - View recent documents\n"
            "/sources - List all connected sources\n"
            "/help - Get help\n\n"
            "मुझे समझ नहीं आ रहा कि आप क्या करना चाहते हैं। इनमें से किसी एक कमांड का उपयोग करने का प्रयास करें:\n"
            "/start - बॉट शुरू करें\n"
            "/connect - किसी चैनल या ग्रुप से कनेक्ट करें\n"
            "/search - दस्तावेज़ खोजें\n"
            "/recent - हाल के दस्तावेज़ देखें\n"
            "/sources - सभी जुड़े स्रोतों की सूची देखें\n"
            "/help - मदद प्राप्त करें"
        )

async def fetch_and_index_messages(user_id, source_name, source_id, limit=300):
    """Fetch and index existing messages from a channel or group.
    
    Args:
        user_id: The user requesting the indexing
        source_name: The name/username of the channel or group
        source_id: MongoDB ID of the source document
        limit: Maximum number of messages to fetch (default: 300)
        
    Returns:
        The number of indexed messages
    """
    indexed_count = 0
    
    try:
        # Verify client is connected and authorized
        if not user_client.is_connected() or not await user_client.is_user_authorized():
            logger.warning(f"Cannot fetch messages for {source_name}: client not connected or not authorized")
            return 0
        
        # Try to resolve the entity
        try:
            entity = await user_client.get_entity(source_name)
        except Exception as e:
            # Try with different formats
            try:
                if source_name.isdigit():
                    entity = await user_client.get_entity(int(source_name))
                else:
                    # Try with @ prefix
                    entity = await user_client.get_entity(f"@{source_name}")
            except Exception as inner_e:
                logger.error(f"Could not resolve entity {source_name}: {inner_e}")
                return 0
        
        # Get messages
        messages = []
        
        try:
            # Fetch messages from the channel/group
            async for message in user_client.iter_messages(entity, limit=limit):
                # Check if message has media
                if message.media:
                    messages.append(message)
        except Exception as e:
            logger.error(f"Error fetching messages from {source_name}: {e}")
            return 0
        
        # Process each message
        for message in messages:
            try:
                # Skip messages without media
                if not message.media:
                    continue
                
                # Determine file details
                file_name = "Unnamed file"
                file_type = "unknown"
                file_size = 0
                mime_type = ""
                text_content = message.text or message.caption or ""
                
                # Check message media type and extract details
                if hasattr(message.media, 'document'):
                    # Document (file)
                    doc = message.media.document
                    file_size = doc.size
                    mime_type = doc.mime_type or ""
                    
                    # Get file type from mime type
                    if mime_type:
                        file_type = mime_type.split('/')[-1] if '/' in mime_type else mime_type
                        
                    # Get filename from attributes
                    for attr in doc.attributes:
                        if hasattr(attr, 'file_name') and attr.file_name:
                            file_name = attr.file_name
                            if '.' in file_name and not file_type:
                                file_type = file_name.split('.')[-1]
                            break
                            
                elif hasattr(message.media, 'photo'):
                    # Photo
                    file_type = "photo"
                    mime_type = "image/jpeg"
                    file_name = f"photo_{message.id}.jpg"
                    
                elif hasattr(message.media, 'video'):
                    # Video
                    file_type = "video"
                    mime_type = "video/mp4"
                    file_name = f"video_{message.id}.mp4"
                    
                elif hasattr(message.media, 'audio'):
                    # Audio
                    file_type = "audio"
                    mime_type = "audio/mp3"
                    file_name = f"audio_{message.id}.mp3"
                    
                # Generate a file hash for deduplication
                file_hash = hashlib.md5(f"{entity.id}_{message.id}_{file_name}".encode()).hexdigest()
                
                # Store original message details for later retrieval
                original_message = {
                    'chat_id': entity.id,
                    'message_id': message.id
                }
                
                # Skip if this file is already indexed for this user
                existing_doc = documents_collection.find_one({
                    'user_id': user_id,
                    'file_hash': file_hash
                })
                
                if existing_doc:
                    logger.info(f"Document already exists for user {user_id}, skipping")
                    continue
                    
                # Add document to database
                document_data = {
                    'user_id': user_id,
                    'source_id': str(source_id),
                    'source_name': getattr(entity, 'title', source_name),
                    'file_name': file_name,
                    'file_type': file_type,
                    'file_size': file_size,
                    'mime_type': mime_type,
                    'file_hash': file_hash,
                    'text': text_content,
                    'date': message.date,
                    'original_message': original_message,
                    'indexed_at': datetime.now()
                }
                
                # Insert document into database
                documents_collection.insert_one(document_data)
                indexed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing message {message.id}: {e}")
                continue
        
        return indexed_count
        
    except Exception as e:
        logger.error(f"Error in fetch_and_index_messages: {e}")
        return indexed_count

async def process_new_message(event):
    """Process new messages in channels/groups the bot is monitoring."""
    if not mongo_available:
        return
        
    try:
        # Get the message
        message = event.message
        
        # Check if message has no media, skip it
        if not message.media:
            return
            
        # Get the chat where the message was sent
        chat = await event.get_chat()
        
        # Get chat info (username or ID)
        chat_username = chat.username if hasattr(chat, 'username') else str(chat.id)
        chat_title = getattr(chat, 'title', chat_username)
        
        logger.info(f"Processing new message from {chat_username} ({chat_title})")
        
        # Find sources that match this chat
        sources = list(sources_collection.find({'source_name': chat_username}))
        
        if not sources:
            # This chat isn't being monitored by any user
            logger.info(f"No users monitoring {chat_username}, skipping")
            return
            
        # Determine file details
        file_name = "Unnamed file"
        file_type = "unknown"
        file_size = 0
        mime_type = ""
        text_content = message.text or message.caption or ""
        
        # Check message media type and extract details
        if hasattr(message.media, 'document'):
            # Document (file)
            doc = message.media.document
            file_size = doc.size
            mime_type = doc.mime_type or ""
            
            # Get file type from mime type
            if mime_type:
                file_type = mime_type.split('/')[-1] if '/' in mime_type else mime_type
                
            # Get filename from attributes
            for attr in doc.attributes:
                if hasattr(attr, 'file_name') and attr.file_name:
                    file_name = attr.file_name
                    if '.' in file_name and not file_type:
                        file_type = file_name.split('.')[-1]
                    break
                    
        elif hasattr(message.media, 'photo'):
            # Photo
            file_type = "photo"
            mime_type = "image/jpeg"
            file_name = f"photo_{message.id}.jpg"
            
        elif hasattr(message.media, 'video'):
            # Video
            file_type = "video"
            mime_type = "video/mp4"
            file_name = f"video_{message.id}.mp4"
            
        elif hasattr(message.media, 'audio'):
            # Audio
            file_type = "audio"
            mime_type = "audio/mp3"
            file_name = f"audio_{message.id}.mp3"
            
        # Generate a file hash for deduplication
        file_hash = hashlib.md5(f"{chat.id}_{message.id}_{file_name}".encode()).hexdigest()
        
        # Store original message details for later retrieval
        original_message = {
            'chat_id': chat.id,
            'message_id': message.id
        }
        
        # Process for each user monitoring this channel
        for source in sources:
            user_id = source['user_id']
            
            # Skip if this file is already indexed for this user
            existing_doc = documents_collection.find_one({
                'user_id': user_id,
                'file_hash': file_hash
            })
            
            if existing_doc:
                logger.info(f"Document already exists for user {user_id}, skipping")
                continue
                
            # Add document to database
            document_data = {
                'user_id': user_id,
                'source_id': str(source.get('_id', 'unknown')),
                'source_name': chat_title,
                'file_name': file_name,
                'file_type': file_type,
                'file_size': file_size,
                'mime_type': mime_type,
                'file_hash': file_hash,
                'text': text_content,
                'date': message.date,
                'original_message': original_message,
                'indexed_at': datetime.now()
            }
            
            # Insert document into database
            result = documents_collection.insert_one(document_data)
            
            logger.info(f"Indexed new file: {file_name} (type: {file_type}) for user {user_id}")
            
    except Exception as e:
        logger.error(f"Error processing new message: {str(e)}", exc_info=True)

async def reindex_source(update: Update, context: ContextTypes.DEFAULT_TYPE, source_id: str) -> None:
    """Reindex messages from an existing source."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Check if MongoDB is available
    if not mongo_available:
        await query.answer("MongoDB is not available")
        await query.edit_message_text(
            "MongoDB is not available. Please try again later.\n\n"
            "MongoDB उपलब्ध नहीं है। कृपया बाद में पुनः प्रयास करें।"
        )
        return
    
    try:
        # Convert ObjectID if needed
        if isinstance(source_id, str):
            try:
                source_id_obj = ObjectId(source_id)
            except:
                await query.answer("Invalid source ID")
                return
        else:
            source_id_obj = source_id
            
        # Get the source from database
        source = sources_collection.find_one({"_id": source_id_obj, "user_id": user_id})
        
        if not source:
            await query.answer("Source not found or access denied")
            return
            
        source_name = source.get('source_name', 'Unknown source')
        
        # Update the message to show progress
        await query.answer()
        status_message = await query.edit_message_text(
            f"Starting to reindex messages from {source_name}... This may take a while.\n\n"
            f"{source_name} से संदेशों को फिर से इंडेक्स करना शुरू कर रहा है... इसमें कुछ समय लग सकता है।"
        )
        
        # Fetch and index messages (using a larger limit for reindexing)
        indexed_count = await fetch_and_index_messages(user_id, source_name, source_id_obj, limit=500)
        
        # Update the message with results
        await status_message.edit_text(
            f"Successfully reindexed {source_name}!\n"
            f"Indexed {indexed_count} messages from this source.\n\n"
            f"{source_name} को सफलतापूर्वक फिर से इंडेक्स किया गया!\n"
            f"इस स्रोत से {indexed_count} संदेशों को इंडेक्स किया गया।"
        )
        
    except Exception as e:
        logger.error(f"Error reindexing source: {e}")
        await query.edit_message_text(
            f"Error reindexing source: {str(e)}\n\n"
            f"स्रोत को फिर से इंडेक्स करने में त्रुटि: {str(e)}"
        )

async def sources_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all sources the user has connected to."""
    user_id = update.effective_user.id
    
    # Check if MongoDB is available
    if not mongo_available:
        await update.message.reply_text(
            "MongoDB is not available. Please try again later.\n\n"
            "MongoDB उपलब्ध नहीं है। कृपया बाद में पुनः प्रयास करें।"
        )
        return
    
    # Get all sources for this user
    user_sources = list(sources_collection.find({"user_id": user_id}))
    
    if not user_sources:
        await update.message.reply_text(
            "You haven't connected to any channels or groups yet. Use /connect to add a source.\n\n"
            "आपने अभी तक किसी चैनल या ग्रुप से कनेक्ट नहीं किया है। स्रोत जोड़ने के लिए /connect का उपयोग करें।"
        )
        return
    
    # Create a message listing all sources
    message = "Your connected sources:\n\n"
    message_hindi = "आपके जुड़े हुए स्रोत:\n\n"
    
    # Create keyboard with buttons for each source
    keyboard = []
    
    for i, source in enumerate(user_sources, 1):
        source_name = source.get("source_name", "Unknown")
        date_added = source.get("date_added", datetime.now()).strftime("%Y-%m-%d")
        
        message += f"{i}. {source_name} (added on {date_added})\n"
        message_hindi += f"{i}. {source_name} ({date_added} को जोड़ा गया)\n"
        
        # Add button to reindex this source
        keyboard.append([InlineKeyboardButton(
            f"Reindex {source_name}", 
            callback_data=f"reindex_{source['_id']}"
        )])
    
    message += "\nClick a button below to reindex messages from a source:"
    message_hindi += "\nकिसी स्रोत से संदेशों को फिर से इंडेक्स करने के लिए नीचे एक बटन पर क्लिक करें:"
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        message + "\n\n" + message_hindi,
        reply_markup=reply_markup
    )

def main() -> None:
    """Start the bot."""
    global user_client
    
    # Create directories if they don't exist
    os.makedirs("downloads", exist_ok=True)
    os.makedirs("sessions", exist_ok=True)
    
    # Cleanup old downloads on startup
    asyncio.get_event_loop().run_until_complete(cleanup_downloads())
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("connect", connect_command))
    application.add_handler(CommandHandler("search", search_in_sources))
    application.add_handler(CommandHandler("recent", recent_command))
    application.add_handler(CommandHandler("sources", sources_command))
    application.add_handler(CommandHandler("auth", auth_command))
    
    # Add callback query handler
    application.add_handler(CallbackQueryHandler(button_click))
    
    # Handle text messages based on user state in the handle_message function
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Error handler - temporarily commented out
    # application.add_error_handler(error_handler)
    
    # Simple approach to check authorization
    loop = asyncio.get_event_loop()
    
    # Connect the client
    loop.run_until_complete(user_client.connect())
    
    # Check if already authorized
    is_authorized = loop.run_until_complete(user_client.is_user_authorized())
    
    if is_authorized:
        logger.info("User already authorized, using existing session")
        # Also update the database to reflect the authorized status
        if mongo_available:
            users_collection.update_one(
                {"user_id": 0},  # System user for global auth status
                {"$set": {"is_authenticated": True, "authenticated_at": datetime.now()}},
                upsert=True
            )
        
        # Add event handler for new messages in channels/groups
        user_client.add_event_handler(process_new_message, events.NewMessage)
        logger.info("Added event handler for new messages")
    else:
        logger.info("User not authorized, starting with bot token")
        user_client.start(bot_token=BOT_TOKEN)
    
    # Schedule periodic cleanup of downloads - temporarily commented out due to missing job_queue
    # application.job_queue.run_repeating(
    #     lambda context: asyncio.ensure_future(cleanup_downloads()),
    #     interval=12*3600,  # Run every 12 hours
    #     first=12*3600      # Start after 12 hours
    # )
    
    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    logger.info("Bot started successfully!")

if __name__ == '__main__':
    main() 