// MongoDB initialization script
// This script runs when the MongoDB container starts for the first time

// Switch to the telegram_search_bot database
db = db.getSiblingDB('telegram_search_bot');

// Create collections with indexes for better performance
db.createCollection('documents');
db.createCollection('users');
db.createCollection('sources');

// Create indexes for better query performance
db.documents.createIndex({ "user_id": 1 });
db.documents.createIndex({ "file_hash": 1 });
db.documents.createIndex({ "text": "text", "content_searchable": "text", "file_name": "text" });
db.documents.createIndex({ "date": -1 });
db.documents.createIndex({ "source_id": 1 });
db.documents.createIndex({ "user_id": 1, "date": -1 });

db.users.createIndex({ "user_id": 1 }, { unique: true });
db.users.createIndex({ "username": 1 });

db.sources.createIndex({ "user_id": 1 });
db.sources.createIndex({ "source_name": 1 });
db.sources.createIndex({ "user_id": 1, "source_name": 1 }, { unique: true });

// Create a user for the application (optional)
// You can uncomment and modify these lines if you want to create a specific user
/*
db.createUser({
    user: "telegram_bot_user",
    pwd: "your_secure_password",
    roles: [
        {
            role: "readWrite",
            db: "telegram_search_bot"
        }
    ]
});
*/

print('MongoDB initialization completed successfully!');
print('Collections created: documents, users, sources');
print('Indexes created for optimal performance');
