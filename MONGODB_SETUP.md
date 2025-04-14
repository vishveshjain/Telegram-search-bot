# MongoDB Setup Guide

The Telegram Search Bot requires MongoDB to store and search documents. This guide explains how to set up MongoDB for use with this bot.

## Option 1: Installing MongoDB Locally (Recommended for Development)

### Windows

1. **Download MongoDB Community Server:**
   - Go to [MongoDB Download Center](https://www.mongodb.com/try/download/community)
   - Select "Windows" as the platform
   - Choose the MSI package and download

2. **Install MongoDB:**
   - Run the downloaded MSI installer
   - Choose "Complete" installation
   - You can choose to install MongoDB Compass (a GUI tool) if desired

3. **Start MongoDB Service:**
   - The installer should configure MongoDB as a Windows service that starts automatically
   - To check if it's running, open Services (Run → services.msc) and look for "MongoDB"
   - If it's not running, right-click and select "Start"

4. **Verify Connection:**
   - The bot should now be able to connect to MongoDB using the default connection string:
   ```
   MONGO_URI=mongodb://localhost:27017/
   ```

### Linux (Ubuntu/Debian)

1. **Import MongoDB Public Key:**
   ```
   wget -qO - https://www.mongodb.org/static/pgp/server-7.0.asc | sudo apt-key add -
   ```

2. **Create List File:**
   ```
   echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu $(lsb_release -cs)/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
   ```

3. **Update Package Database:**
   ```
   sudo apt-get update
   ```

4. **Install MongoDB:**
   ```
   sudo apt-get install -y mongodb-org
   ```

5. **Start MongoDB Service:**
   ```
   sudo systemctl start mongod
   ```

6. **Enable MongoDB to Start on Boot:**
   ```
   sudo systemctl enable mongod
   ```

7. **Verify Status:**
   ```
   sudo systemctl status mongod
   ```

## Option 2: Using MongoDB Atlas (Cloud Database)

MongoDB Atlas provides a free tier with 512MB of storage, which is sufficient for this bot.

1. **Create an Account:**
   - Go to [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register)
   - Sign up for a free account

2. **Create a Cluster:**
   - Click "Build a Database"
   - Choose the free M0 tier
   - Select a cloud provider and region (choose ones closest to you)
   - Click "Create Cluster" (this might take a few minutes)

3. **Set Up Database Access:**
   - In the left sidebar, go to "Database Access"
   - Click "Add New Database User"
   - Create a username and password (remember these!)
   - Set privileges to "Read and Write to Any Database"
   - Click "Add User"

4. **Configure Network Access:**
   - In the left sidebar, go to "Network Access"
   - Click "Add IP Address"
   - To allow access from anywhere, click "Allow Access from Anywhere" (not recommended for production)
   - For better security, add only your specific IP address
   - Click "Confirm"

5. **Get Connection String:**
   - Go back to the Clusters overview
   - Click "Connect"
   - Select "Connect your application"
   - Choose the Driver as "Python" and version "3.6 or later"
   - Copy the connection string
   - Replace `<password>` with your database user password
   - Replace `<dbname>` with `telegram_search_bot`

6. **Update .env File:**
   Replace the MONGO_URI in your .env file with the connection string from Atlas:
   ```
   MONGO_URI=mongodb+srv://username:password@cluster0.example.mongodb.net/telegram_search_bot
   ```

## Troubleshooting

### Connection Refused Error

If you see: "No connection could be made because the target machine actively refused it"

**Solution:**
1. Check if MongoDB service is running
2. Try connecting with MongoDB Compass to verify the connection
3. Ensure your firewall allows connections to port 27017

### Authentication Failed

If you see authentication errors with MongoDB Atlas:

**Solution:**
1. Double-check username and password in connection string
2. Ensure you've replaced `<password>` with your actual password
3. Check that the user has the correct permissions

### Slow Connection

If the bot seems slow when connecting to MongoDB:

**Solution:**
1. For Atlas, choose a region closer to your location
2. For local MongoDB, check system resources and consider increasing RAM allocation 