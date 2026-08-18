# backend_BO/app/__init__.py

from flask import Flask
from flask_cors import CORS
from . import data_loader

def create_app():
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False  # Arabic JSON

    # Optional gzip compression (recommended for 20k results)
    # pip install flask-compress
    try:
        from flask_compress import Compress
        Compress(app)
    except Exception:
        pass

    data_loader.load_chunks()
    
    from . import services
    services._ensure_caches()


    from .routes import main_bp
    app.register_blueprint(main_bp)

    CORS(app)
    return app
