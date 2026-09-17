"""Flask application factory."""
from __future__ import annotations

import json

from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .db import init_db
from .llm.client import auth_source


def create_app() -> Flask:
    app = Flask(__name__)
    if Config.TRUSTED_PROXY_HOPS > 0:
        # trust X-Forwarded-For only for the known number of proxy hops (Vercel: 1)
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=Config.TRUSTED_PROXY_HOPS, x_proto=Config.TRUSTED_PROXY_HOPS)
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
        # every abort() becomes JSON the frontend can show; keep werkzeug's status and headers (e.g. Allow on 405)
        resp = e.get_response()
        resp.data = json.dumps({"error": e.description, "status": e.code})
        resp.content_type = "application/json"
        return resp

    return app
