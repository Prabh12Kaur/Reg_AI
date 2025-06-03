from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
import os

socketio = SocketIO(cors_allowed_origins="*")

def create_app():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    root_dir = os.path.abspath(os.path.join(base_dir, ".."))

    app = Flask(__name__,
                template_folder=os.path.join(root_dir, "templates"),
                static_folder=os.path.join(root_dir, "static"))

    CORS(app)

    from .announcement_api import announcement_bp
    from .scan_api import scan_bp
    from .token_api import token_bp

    app.register_blueprint(announcement_bp)
    app.register_blueprint(scan_bp)
    app.register_blueprint(token_bp)

    socketio.init_app(app)
    return app