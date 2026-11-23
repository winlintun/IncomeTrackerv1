from datetime import timedelta
import secrets
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from extensions import bcrypt, get_dummy_password_hash
from models import Expense, IncomeRecord, Job, MAX_USERNAME_LEN, Note, PasswordResetToken, Setting, User, db
from security import clear_csrf_token, get_csrf_token, rate_limit
from validators import (
    _clean_str,
    _find_user_by_username,
    _hash_reset_token,
    _json_body,
    _normalize_username,
    _require_body,
    _valid_password,
    _validate_credentials,
    utcnow,
)

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/api/auth/csrf-token', methods=['GET'])
def csrf_token_endpoint():
    return jsonify({'csrf_token': get_csrf_token()})


@auth_bp.route('/api/auth/register', methods=['POST'])
@rate_limit(5, 60, 'auth_register')
def register():
    data = _json_body()
    if data is None:
        return jsonify({'error': 'Invalid request body'}), 400
    username, password = _validate_credentials(data, min_password_len=6)
    if not username or not password:
        return jsonify({'error': 'Username is required (max 80 chars) and password must be 6 to 72 bytes'}), 400

    if _find_user_by_username(username):
        return jsonify({'error': 'Username already exists'}), 400

    hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
    new_user = User(username=username, password_hash=hashed_pw)

    bootstrap = Setting.query.filter_by(key='admin_bootstrap_done').first()
    is_first_ever = bootstrap is None and User.query.count() == 0
    if is_first_ever:
        new_user.role = 'admin'
        db.session.add(Setting(key='admin_bootstrap_done', value='1'))
    else:
        new_user.role = 'user'
        if bootstrap is None:
            db.session.add(Setting(key='admin_bootstrap_done', value='1'))

    db.session.add(new_user)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        if _find_user_by_username(username):
            return jsonify({'error': 'Username already exists'}), 400
        raise
    return jsonify({'message': 'User created successfully'}), 201


@auth_bp.route('/api/auth/login', methods=['POST'])
@rate_limit(10, 60, 'auth_login')
def login():
    data = _json_body() or {}
    username, password = _validate_credentials(data)
    if not username or not password:
        return jsonify({'error': 'Invalid credentials'}), 401

    user = _find_user_by_username(username)
    try:
        if user:
            valid = bcrypt.check_password_hash(user.password_hash, password)
        else:
            valid = bcrypt.check_password_hash(get_dummy_password_hash(), password)
    except ValueError:
        valid = False
    if valid and user:
        login_user(user)
        return jsonify({
            'id': user.id,
            'username': user.username,
            'role': user.role
        })
    return jsonify({'error': 'Invalid credentials'}), 401


@auth_bp.route('/api/auth/forgot-password', methods=['POST'])
@rate_limit(5, 300, 'auth_forgot')
def forgot_password():
    data = _json_body()
    if data is None:
        return jsonify({'error': 'Invalid request body'}), 400
    username = data.get('username')
    if not isinstance(username, str):
        return jsonify({'error': 'Username must be a string'}), 400
    username = username.strip()
    user = _find_user_by_username(username)

    generic_message = (
        'If this account exists, a reset code has been generated (it expires in 30 minutes). '
        'The code is printed in the server logs or can be provided by an admin.'
    )

    if user:
        token = secrets.token_hex(16)
        token_hash = _hash_reset_token(token)
        expires_at = utcnow() + timedelta(minutes=30)
        PasswordResetToken.query.filter_by(user_id=user.id, used=False).update({'used': True})
        db.session.add(PasswordResetToken(user_id=user.id, token=token_hash, expires_at=expires_at))
        db.session.commit()

        current_app.logger.info('Password reset requested for user id %s', user.id)

        response = {'message': generic_message}
        if current_user.is_authenticated and current_user.role == 'admin':
            response['reset_token'] = token
        return jsonify(response), 200
    return jsonify({'message': generic_message}), 200


@auth_bp.route('/api/auth/reset-password', methods=['POST'])
@rate_limit(10, 300, 'auth_reset')
def reset_password():
    data = _json_body()
    if data is None:
        return jsonify({'error': 'Invalid request body'}), 400
    username = data.get('username')
    token = data.get('token')
    if not isinstance(username, str) or not isinstance(token, str):
        return jsonify({'error': 'Username and reset code must be strings'}), 400
    username = username.strip()
    token = token.strip()
    new_password = data.get('new_password')
    if not username or not token:
        return jsonify({'error': 'Username and reset code are required'}), 400
    if not _valid_password(new_password, min_len=6):
        return jsonify({'error': 'Password must be 6 to 72 bytes'}), 400

    token_hash = _hash_reset_token(token)
    reset = PasswordResetToken.query.filter_by(token=token_hash, used=False).first()
    if not reset or utcnow() > reset.expires_at:
        return jsonify({'error': 'Invalid or expired reset code'}), 400

    user = db.session.get(User, reset.user_id)
    if not user or _normalize_username(user.username) != _normalize_username(username):
        return jsonify({'error': 'Invalid or expired reset code'}), 400

    user.password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
    PasswordResetToken.query.filter_by(user_id=user.id, used=False).update({'used': True})
    db.session.commit()
    return jsonify({'message': 'Password updated. You can now sign in.'})


@auth_bp.route('/api/auth/change-password', methods=['POST'])
@login_required
@rate_limit(5, 300, 'auth_change_password')
def change_password():
    data, error = _require_body()
    if error:
        return error

    current_password = data.get('current_password')
    new_password = data.get('new_password')
    if not isinstance(current_password, str) or not current_password:
        return jsonify({'error': 'Current password is required'}), 400
    if not _valid_password(new_password, min_len=6):
        return jsonify({'error': 'Password must be 6 to 72 bytes'}), 400

    try:
        valid = bcrypt.check_password_hash(current_user.password_hash, current_password)
    except ValueError:
        valid = False
    if not valid:
        return jsonify({'error': 'Current password is incorrect'}), 400

    current_user.password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
    PasswordResetToken.query.filter_by(user_id=current_user.id, used=False).update({'used': True})
    db.session.commit()
    return jsonify({'message': 'Password updated successfully'})


@auth_bp.route('/api/auth/profile', methods=['GET', 'PUT'])
@login_required
def manage_profile():
    if request.method == 'PUT':
        data, error = _require_body()
        if error:
            return error

        if 'username' in data:
            raw_username = data.get('username')
            if not isinstance(raw_username, str):
                return jsonify({'error': 'Username must be a string'}), 400
            username = _clean_str(raw_username, MAX_USERNAME_LEN)
            if username is None:
                return jsonify({'error': f'username must be at most {MAX_USERNAME_LEN} characters'}), 400
            if not username:
                return jsonify({'error': 'Username is required'}), 400
            existing = _find_user_by_username(username)
            if existing and existing.id != current_user.id:
                return jsonify({'error': 'Username already exists'}), 400
            current_user.username = username

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': 'Username already exists'}), 400

        return jsonify({
            'id': current_user.id,
            'username': current_user.username,
            'role': current_user.role
        })

    return jsonify({
        'id': current_user.id,
        'username': current_user.username,
        'role': current_user.role,
        'stats': {
            'jobs_count': Job.query.filter_by(user_id=current_user.id).count(),
            'income_records_count': IncomeRecord.query.filter_by(user_id=current_user.id).count(),
            'expenses_count': Expense.query.filter_by(user_id=current_user.id).count(),
            'notes_count': Note.query.filter_by(user_id=current_user.id).count(),
        }
    })


@auth_bp.route('/api/auth/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    clear_csrf_token()
    return jsonify({'message': 'Logged out'})


@auth_bp.route('/api/auth/me')
def me():
    if current_user.is_authenticated:
        return jsonify({
            'id': current_user.id,
            'username': current_user.username,
            'role': current_user.role
        })
    return jsonify(None)
