from app import create_app
from flask import send_from_directory
import os
from flask_cors import CORS

app = create_app()
CORS(app)

BOOKS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "book_documents"))

@app.route('/static/book_documents/<path:filepath>')
def serve_book_file(filepath):
    return send_from_directory(BOOKS_DIR, filepath)

if __name__ == "__main__":
    # ✅ Waitress instead of Flask dev server
    #from waitress import serve

    # threads: increase if you have many concurrent users/requests
    #serve(app, host="0.0.0.0", port=5000, threads=8)
    app.run(host="0.0.0.0", port=5000, debug=True)
