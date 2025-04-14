# Telegram Search Bot Setup Guide

This document provides detailed instructions on how to set up and use the Telegram Search Bot.

## Prerequisites

1. Python 3.8+
2. MongoDB (local installation or cloud service like MongoDB Atlas)
3. Telegram account
4. Basic familiarity with command line operations

## Step-by-Step Setup

### 1. Get Telegram API Credentials

1. Visit https://my.telegram.org/apps
2. Log in with your phone number
3. Create a new application if you don't have one
4. Note down the `api_id` and `api_hash` values

### 2. Create a Telegram Bot

1. Open Telegram and search for @BotFather
2. Start a chat and type `/newbot`
3. Follow the instructions to create a new bot
4. Note down the bot token provided by BotFather

### 3. Set Up MongoDB

#### Local MongoDB:
1. [Install MongoDB](https://www.mongodb.com/docs/manual/installation/)
2. Start MongoDB service
3. Use `mongodb://localhost:27017/` as your connection string

#### MongoDB Atlas (Cloud):
1. Create account at [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
2. Create a new cluster
3. Set up database access (username/password)
4. Get your connection string with your credentials

### 4. Configure Environment Variables

1. Copy `.env.example` to `.env`
2. Fill in your API credentials, bot token, and MongoDB URI

### 5. Install Dependencies

```
pip install -r requirements.txt
```

### 6. Run the Bot

```
python bot.py
```

## Usage Guide

### Bot Commands

- `/start` - Start the bot and see main menu
- `/help` - Show help information
- `/connect` - Connect to a Telegram channel or group
- `/search` - Search for documents
- `/recent` - View recently added documents

### Connecting to a Channel/Group

1. Use `/connect` command
2. Send the username (@channel_name) or link (https://t.me/channel_name) of the target channel/group
3. The bot will start collecting documents from the channel/group

### Searching for Documents

1. Use `/search` command
2. Enter keywords related to the document you want to find
3. The bot will return matching documents

## Troubleshooting

### Bot Cannot Access Private Channel/Group

Make sure:
1. The bot is added as a member of the channel/group
2. The bot has sufficient permissions to read messages

### Connection Issues

Check:
1. Internet connection
2. MongoDB is running
3. API credentials are correct

### Performance Considerations

- The bot currently limits collection to 1000 messages per channel to avoid performance issues
- For larger channels, consider increasing this limit but be aware of memory usage 