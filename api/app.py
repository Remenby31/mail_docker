# app.py
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from functools import wraps
from typing import List, Optional
from datetime import datetime
import asyncio
from dotenv import load_dotenv
import os

from email_analyzer import EmailAnalyzer

# Load environment variables
load_dotenv()

app = Flask(__name__, static_url_path='', static_folder='static')
CORS(app)
email_analyzer = None

# Utility decorator to handle async routes
def async_route(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapped

# Error handler for generic exceptions
@app.errorhandler(Exception)
def handle_error(error):
    return jsonify({
        "error": str(error),
        "status": "error"
    }), 500

def get_analyzer():
    """
    Get or initialize the analyzer
    """
    global email_analyzer
    if email_analyzer is None:
        try:
            email_analyzer = EmailAnalyzer()
            asyncio.run(email_analyzer.setup_vector_store())
        except Exception as e:
            app.logger.error(f"Failed to initialize analyzer: {str(e)}")
            raise
    return email_analyzer

# Middleware to check if analyzer is initialized
def require_analyzer():
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            try:
                analyzer = get_analyzer()
                return f(*args, **kwargs)
            except Exception as e:
                return jsonify({
                    "error": "Service initialization failed: " + str(e),
                    "status": "error"
                }), 503
        return wrapped
    return decorator

# Routes
@app.route('/')
def index():
    return app.send_static_file('index.html')

#health
@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

@app.route('/api/v1/search', methods=['POST'])
@require_analyzer()
@async_route
async def search_emails():
    """
    Search emails using natural language query
    """
    try:
        data = request.get_json()
        if not data or 'question' not in data:
            return jsonify({
                "error": "Missing required field 'question'",
                "status": "error"
            }), 400

        question = data['question']
        limit = data.get('limit', 3)

        answer, relevant_emails = await email_analyzer.search_with_context(question, limit, score_threshold=0.5)
        
        response = {
            "status": "success",
            "answer": answer,
            "relevant_emails": [
                {
                    "sender": email.metadata["sender"],
                    "subject": email.metadata["subject"],
                    "date": email.metadata["date"],
                    "body": email.page_content,
                    "email_id": email.metadata["email_id"]
                }
                for email in relevant_emails
            ]
        }
        
        return jsonify(response)

    except Exception as e:
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500

@app.route('/api/v1/status', methods=['GET'])
@require_analyzer()
def get_status():
    """
    Get system status
    """
    try:
        return jsonify({
            "status": "operational",
            "database_hash": email_analyzer.get_db_hash(),
            "last_update": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500

@app.route('/api/v1/refresh', methods=['POST'])
@require_analyzer()
@async_route
async def refresh_vector_store():
    """
    Force refresh of vector store
    """
    try:
        await email_analyzer.setup_vector_store(force_refresh=True)
        return jsonify({
            "status": "success",
            "message": "Vector store refreshed successfully"
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500

# Initialize the analyzer on first request that needs it
@app.route('/api/v1/initialize', methods=['POST'])
@async_route
async def initialize_analyzer():
    """
    Explicitly initialize the analyzer
    """
    try:
        get_analyzer()
        return jsonify({
            "status": "success",
            "message": "Analyzer initialized successfully"
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)