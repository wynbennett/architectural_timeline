"""Flask application factory."""
from __future__ import annotations

from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from .config import Config
from .db import init_db
from .llm.client import auth_source


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    init_db()

    from .routes.repos import bp as repos_bp
    from .routes.graphs import bp as graphs_bp
    from .routes.files import bp as files_bp
    from .routes.jobs import bp as jobs_bp
    from .routes.chat import bp as chat_bp
    from .routes.compare import bp as compare_bp

    for bp in (repos_bp, graphs_bp, files_bp, jobs_bp, chat_bp, compare_bp):
        app.register_blueprint(bp, url_prefix="/api")

    @app.get("/api/health")
    def health():
        return jsonify(
            {
                "ok": True,
                "generation_enabled": Config.GENERATION_ENABLED,
                "generation_mode": Config.GENERATION_MODE,
                "demo_mode": Config.DEMO_MODE,
                "db": "sqlite" if Config.is_sqlite() else "postgres",
                "file_source": Config.FILE_SOURCE,
                "model": Config.MODEL,
                "auth": auth_source(),
            }
        )

    @app.errorhandler(HTTPException)
    def http_error(e: HTTPException):
        # every abort() becomes JSON the frontend can show
        return jsonify({"error": e.description if e.code != 404 else "not found", "status": e.code}), e.code

    return app
