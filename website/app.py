import os
import re
from flask import Flask, request, jsonify, send_from_directory, send_file, abort, Response, stream_with_context
from pymongo import MongoClient
from dotenv import load_dotenv
from bson.objectid import ObjectId
from telethon.sync import TelegramClient
import io
import asyncio
import requests
import logging
import mimetypes

# Load environment variables from project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# Fix event loop for Telethon sync: create a single loop at startup
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# MongoDB setup
db_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
client = MongoClient(db_uri)
db = client['telegram_search_bot']
collection = db['documents']

# Initialize Flask app
app = Flask(__name__)
app.logger.setLevel(logging.DEBUG)

# Telethon client setup (use .session file)
API_ID = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH', '')
SESSION_FILE = os.path.join(os.path.dirname(__file__), '+919205010115.session')
tele_client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
tele_client.start()

@app.route('/css/<path:filename>')
def serve_css(filename):
    return send_from_directory('css', filename)

@app.route('/js/<path:filename>')
def serve_js(filename):
    return send_from_directory('js', filename)

@app.route('/media/<path:filename>')
def serve_media(filename):
    # Stream local downloaded media with Range support
    media_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'downloads'))
    file_path = os.path.join(media_dir, filename)
    if not os.path.isfile(file_path):
        abort(404)
    range_header = request.headers.get('Range', None)
    if not range_header:
        # Serve full file
        mime = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
        return send_file(file_path, mimetype=mime)
    # Parse byte range
    size = os.path.getsize(file_path)
    byte1, byte2 = 0, None
    m = re.search(r'bytes=(\d+)-(\d*)', range_header)
    if m:
        g1, g2 = m.groups()
        byte1 = int(g1)
        if g2:
            byte2 = int(g2)
    byte2 = byte2 if byte2 is not None else size - 1
    length = byte2 - byte1 + 1
    with open(file_path, 'rb') as f:
        f.seek(byte1)
        data = f.read(length)
    rv = Response(data, 206, mimetype=mimetypes.guess_type(file_path)[0] or 'application/octet-stream', direct_passthrough=True)
    rv.headers.add('Content-Range', f'bytes {byte1}-{byte2}/{size}')
    rv.headers.add('Accept-Ranges', 'bytes')
    rv.headers.add('Content-Length', str(length))
    return rv

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/media/<doc_id>')
def api_media(doc_id):
    app.logger.debug(f"[api_media] called with doc_id={doc_id}")
    # Fetch document
    try:
        doc = collection.find_one({'_id': ObjectId(doc_id)})
        app.logger.debug(f"[api_media] doc from DB: {doc}")
    except:
        return jsonify({'error': 'Invalid document ID'}), 400
    if not doc:
        return jsonify({'error': 'Document not found'}), 404
    orig = doc.get('original_message', {})
    app.logger.debug(f"[api_media] original_message: {orig}")
    chat_id = orig.get('chat_id')
    message_id = orig.get('message_id')
    app.logger.debug(f"[api_media] chat_id: {chat_id}, message_id: {message_id}")
    if not chat_id or not message_id:
        return jsonify({'error': 'Original message missing'}), 400
    # Resolve the chat entity first
    try:
        entity = tele_client.get_entity(chat_id)
        app.logger.debug(f"[api_media] resolved entity: {entity}")
    except Exception as e:
        app.logger.error(f"[api_media] get_entity failed: {e}")
        return jsonify({'error': f'Failed to resolve chat entity: {e}'}), 500
    # Fetch Telegram message via Telethon
    messages = tele_client.get_messages(entity, ids=[message_id])
    app.logger.debug(f"[api_media] get_messages returned: {messages}")
    if not messages:
        return jsonify({'error': 'No media found'}), 404
    message = messages[0] if isinstance(messages, (list, tuple)) else messages
    app.logger.debug(f"[api_media] selected message: {message}")
    app.logger.debug(f"[api_media] message.media attribute: {getattr(message, 'media', None)}")
    if not getattr(message, 'media', None):
        return jsonify({'error': 'No media found'}), 404
    # Download media to memory
    buf = io.BytesIO()
    app.logger.debug(f"[api_media] downloading media to buffer")
    tele_client.download_media(message, file=buf)
    app.logger.debug(f"[api_media] download_media complete, buffer size: {buf.getbuffer().nbytes}")
    buf.seek(0)
    # Stream to client
    mimetype = doc.get('mime_type') or 'application/octet-stream'
    return send_file(buf, mimetype=mimetype, as_attachment=False, download_name=doc.get('file_name'))

@app.route('/api/search')
def api_search():
    q = request.args.get('q', '')
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('page_size', 10))
    if not q:
        return jsonify({'error': "Missing 'q' parameter"}), 400
    regex = re.compile(re.escape(q), re.IGNORECASE)
    query = {'$or': [
        {'text': regex},
        {'file_name': regex},
        {'file_type': regex}
    ]}
    total_count = collection.count_documents(query)
    total_pages = -(-total_count // page_size)
    cursor = collection.find(query).sort('date', -1).skip((page-1)*page_size).limit(page_size)
    results = []
    for doc in cursor:
        results.append({
            '_id': str(doc.get('_id')),
            'file_name': doc.get('file_name'),
            'file_type': doc.get('file_type'),
            'mime_type': doc.get('mime_type'),
            'file_hash': doc.get('file_hash'),
            'text': doc.get('text'),
            'date': doc.get('date').isoformat() if doc.get('date') else None,
            'source_name': doc.get('source_name'),
            'chat_id': doc.get('original_message', {}).get('chat_id'),
            'message_id': doc.get('original_message', {}).get('message_id'),
            'media_url': f"/api/media/{doc.get('_id')}"
        })
    return jsonify({'results': results, 'total_count': total_count, 'total_pages': total_pages, 'page': page})

@app.route('/api/source/<source_name>')
def api_source(source_name):
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('page_size', 10))
    query = {'source_name': source_name}
    total_count = collection.count_documents(query)
    total_pages = -(-total_count // page_size)
    cursor = collection.find(query).sort('date', -1).skip((page-1)*page_size).limit(page_size)
    source_results = []
    for doc in cursor:
        source_results.append({
            '_id': str(doc.get('_id')),
            'file_name': doc.get('file_name'),
            'file_type': doc.get('file_type'),
            'mime_type': doc.get('mime_type'),
            'file_hash': doc.get('file_hash'),
            'text': doc.get('text'),
            'date': doc.get('date').isoformat() if doc.get('date') else None,
            'source_name': doc.get('source_name'),
            'chat_id': doc.get('original_message', {}).get('chat_id'),
            'message_id': doc.get('original_message', {}).get('message_id'),
            'media_url': f"/api/media/{doc.get('_id')}"
        })
    return jsonify({'results': source_results, 'total_count': total_count, 'total_pages': total_pages, 'page': page})

@app.route('/api/document/<doc_id>')
def api_document(doc_id):
    try:
        doc = collection.find_one({'_id': ObjectId(doc_id)})
    except Exception:
        return jsonify({'error': 'Invalid document ID'}), 400
    if not doc:
        return jsonify({'error': 'Document not found'}), 404
    return jsonify({
        '_id': str(doc.get('_id')),
        'file_name': doc.get('file_name'),
        'file_type': doc.get('file_type'),
        'mime_type': doc.get('mime_type'),
        'file_hash': doc.get('file_hash'),
        'text': doc.get('text'),
        'date': doc.get('date').isoformat() if doc.get('date') else None,
        'source_name': doc.get('source_name'),
        'chat_id': doc.get('original_message', {}).get('chat_id'),
        'message_id': doc.get('original_message', {}).get('message_id'),
        'media_url': f"/api/media/{doc.get('_id')}"
    })

@app.route('/api/sources')
def api_sources():
    # Aggregate top groups by number of documents
    try:
        limit = int(request.args.get('limit', 6))
    except:
        limit = 6
    pipeline = [
        {"$group": {"_id": "$source_name", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit}
    ]
    sources = []
    for item in collection.aggregate(pipeline):
        sources.append({"source_name": item["_id"], "count": item["count"]})
    return jsonify(sources)

@app.route('/download/<doc_id>')
def download_file(doc_id):
    try:
        doc = collection.find_one({'_id': ObjectId(doc_id)})
    except:
        return jsonify({'error': 'Invalid document ID'}), 400
    if not doc:
        return jsonify({'error': 'Document not found'}), 404
    file_id = doc.get('file_id')
    if not file_id:
        return jsonify({'error': 'No file to download'}), 404
    # Load bot token from TELEGRAM_BOT_TOKEN or fallback to BOT_TOKEN
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('BOT_TOKEN')
    if not bot_token:
        return jsonify({'error': 'Missing bot token (TELEGRAM_BOT_TOKEN or BOT_TOKEN)'}), 500
    info_resp = requests.get(f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}")
    if not info_resp.ok:
        return jsonify({'error': 'Failed to fetch file info'}), 500
    result = info_resp.json().get('result', {})
    file_path_telegram = result.get('file_path')
    if not file_path_telegram:
        return jsonify({'error': 'No file_path returned'}), 500
    tg_file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path_telegram}"
    headers = {}
    range_header = request.headers.get('Range')
    if range_header:
        headers['Range'] = range_header
    tg_resp = requests.get(tg_file_url, headers=headers, stream=True)
    def generate():
        for chunk in tg_resp.iter_content(chunk_size=8192):
            yield chunk
    filename = doc.get('file_name', file_id)
    flask_resp = Response(stream_with_context(generate()), status=tg_resp.status_code, mimetype=tg_resp.headers.get('Content-Type'))
    flask_resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    for h in ['Content-Range', 'Accept-Ranges', 'Content-Length']:
        if h in tg_resp.headers:
            flask_resp.headers[h] = tg_resp.headers[h]
    return flask_resp

if __name__ == '__main__':
    # Run Flask app in single-threaded mode to maintain a consistent asyncio loop
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=False, use_reloader=False)
