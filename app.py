from datetime import timedelta
import os
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, url_for
from sqlalchemy.engine import make_url
from sqlalchemy.pool import StaticPool
from db_init import (
    _backfill_normalized_usernames,
    _drop_duplicate_normalized_users,
    _seed_bootstrap_flag,
    init_db_with_retry,
)
from extensions import bcrypt, login_manager
from models import MAX_USERNAME_LEN, User, db
from routes import register_blueprints
from security import get_csrf_token, rate_limiter, validate_csrf_request
from validators import describe_database_url

load_dotenv()

app = Flask(__name__)
is_development = os.getenv('FLASK_ENV') == 'development' or os.getenv('APP_ENV') == 'development'
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
if not app.config['SECRET_KEY']:
    if not is_development:
        raise RuntimeError(
            'SECRET_KEY is not set. Refusing to start outside development; '
            'set SECRET_KEY to a strong random string.'
        )
    app.config['SECRET_KEY'] = 'dev-secret-key'
    print(
        'WARNING: SECRET_KEY is not set; using an insecure development fallback. '
        'Set the SECRET_KEY environment variable.'
    )

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=not is_development,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    REMEMBER_COOKIE=False,
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
    WTF_CSRF_ENABLED=True,
)

database_url = (os.getenv('DATABASE_URL') or '').strip()
if not database_url:
    if not is_development:
        raise RuntimeError(
            'DATABASE_URL is not set. Refusing to start outside development; '
            'set DATABASE_URL to your PostgreSQL connection string.'
        )
    database_url = 'sqlite:///income_tracker.sqlite'
    print('WARNING: DATABASE_URL is not set; using local SQLite because FLASK_ENV/APP_ENV=development.')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
if database_url.startswith('sqlite'):
    sqlite_path = make_url(database_url).database
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'check_same_thread': False}}
    if sqlite_path in (None, '', ':memory:'):
        app.config['SQLALCHEMY_ENGINE_OPTIONS']['poolclass'] = StaticPool
else:
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
print(f'Database target: {describe_database_url(database_url)}')

db.init_app(app)
bcrypt.init_app(app)
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Authentication required'}), 401
    return redirect(url_for('pages.index'))


@app.context_processor
def inject_csrf_token():
    return {'csrf_token': get_csrf_token}


@app.before_request
def enforce_csrf():
    return validate_csrf_request()


@app.after_request
def set_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'same-origin')
    response.headers.setdefault('X-XSS-Protection', '0')
    if request.path.startswith('/api/'):
        response.headers.setdefault('Cache-Control', 'no-store')
    else:
        response.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com "
            "https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    return response


@app.errorhandler(404)
def handle_404(error):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return error


@app.errorhandler(405)
def handle_405(error):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Method not allowed'}), 405
    return error


@app.errorhandler(400)
def handle_400(error):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Bad request'}), 400
    return error


@app.errorhandler(413)
def handle_413(error):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Request body too large'}), 413
    return error


@app.errorhandler(500)
def handle_500(error):
    db.session.rollback()
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal server error'}), 500
    return error


register_blueprints(app)
init_db_with_retry(app)

__all__ = [
    'app',
    'bcrypt',
    'MAX_USERNAME_LEN',
    '_backfill_normalized_usernames',
    '_drop_duplicate_normalized_users',
    '_seed_bootstrap_flag',
    'rate_limiter',
]

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=False)
