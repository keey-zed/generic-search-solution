# backend_BO/app/__init__.py
#
# NOTE : the Flask app-factory imports below are the legacy
# "artisan" application's bootstrap, not part of the generic search
# factory (`app/core/`, `app/api/`). They are deliberately imported
# lazily, inside `create_app()`, rather than at module import time.
#
# Before this change, `from flask import Flask` at the top of this file
# ran on ANY `import app.something` -- including `import app.core...` or
# `import app.api...` -- which meant the generic core could not be
# imported (or tested) at all without flask/flask_cors installed, even
# though neither is a dependency of the generic core itself. Moving the
# import inside `create_app()` fixes that without changing behavior for
# anyone who does call `create_app()`.
def create_app():
    from flask import Flask
    from flask_cors import CORS
    from . import data_loader

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
