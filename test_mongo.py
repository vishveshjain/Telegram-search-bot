import os
import pymongo
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
MONGO_URI = os.getenv('MONGO_URI', '')

print(f"Connection string: {MONGO_URI}")

try:
    # Try to connect with a short timeout
    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    
    # The ismaster command is cheap and does not require auth
    client.admin.command('ping')
    
    print("MongoDB connection successful!")
    
    # List all databases
    print("\nAvailable databases:")
    for db_name in client.list_database_names():
        print(f"- {db_name}")
    
    # Create test document
    db = client['telegram_search_bot']
    test_collection = db['test']
    
    result = test_collection.insert_one({"test": "document", "time": "now"})
    print(f"\nInserted document ID: {result.inserted_id}")
    
    # Find and display the document
    print("\nFound documents:")
    for doc in test_collection.find():
        print(doc)
    
except pymongo.errors.ServerSelectionTimeoutError:
    print("Error: Could not connect to MongoDB server. Server selection timed out.")
except pymongo.errors.OperationFailure as e:
    print(f"Authentication error: {e}")
except Exception as e:
    print(f"Error: {e}") 