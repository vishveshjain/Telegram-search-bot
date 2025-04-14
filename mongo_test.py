import os
import pymongo
from dotenv import load_dotenv

# Load environment variables
print("Loading environment variables...")
load_dotenv()
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
print(f"MongoDB URI: {MONGO_URI}")

# Use direct connection string
MONGO_URI = 'mongodb://localhost:27017'
print(f"MongoDB URI: {MONGO_URI}")

# Try to connect to MongoDB
print("Connecting to MongoDB...")
try:
    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    # Check connection
    client.admin.command('ping')
    print("MongoDB connection successful!")
    
    # Create database and collections
    db = client['telegram_search_bot']
    documents_collection = db['documents']
    users_collection = db['users']
    sources_collection = db['sources']
    
    # Try to insert a test document
    result = users_collection.insert_one({
        "test": True,
        "message": "This is a test document"
    })
    print(f"Test document inserted with ID: {result.inserted_id}")
    
    # Find the test document
    test_doc = users_collection.find_one({"test": True})
    print(f"Found test document: {test_doc}")
    
    # Clean up by removing the test document
    users_collection.delete_one({"test": True})
    print("Test document removed")
    
except Exception as e:
    print(f"MongoDB connection error: {e}") 