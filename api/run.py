"""Local dev server: python run.py"""
import logging

from app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()

if __name__ == "__main__":
    # threaded so SSE chat and generation polling can overlap
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
