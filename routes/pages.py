from flask import Blueprint, current_app, jsonify, render_template
from flask_login import current_user
from sqlalchemy import text
from models import db
from validators import describe_database_url

pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/api/health/db')
def db_health():
    try:
        db.session.execute(text('SELECT 1'))
    except Exception:
        current_app.logger.exception('Database health check failed')
        return jsonify({'status': 'error'}), 503
    payload = {'status': 'ok'}
    if current_user.is_authenticated and current_user.role == 'admin':
        payload['dialect'] = db.engine.url.get_backend_name()
        payload['target'] = describe_database_url(db.engine.url)
    return jsonify(payload)


@pages_bp.route('/')
def index():
    return render_template('index.html')
