import hashlib
import math
import re
from datetime import datetime, timezone
from functools import wraps
from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.engine import make_url
from models import User, normalize_username, MAX_USERNAME_LEN

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
MONTH_RE = re.compile(r'^\d{4}-\d{2}$')
COLOR_RE = re.compile(r'^#[0-9a-fA-F]{3,8}$')
VALID_ROLES = {'admin', 'user'}
VALID_EXPENSE_TYPES = {'daily', 'bills', 'work', 'one-time'}

MAX_JOB_NAME_LEN = 100
MAX_NOTE_TITLE_LEN = 200
MAX_DESCRIPTION_LEN = 200
MAX_TAGS_LEN = 500
MAX_TAG_LEN = 50
MAX_COLOR_LEN = 20
MAX_MONETARY_AMOUNT = 9999999999.99
MAX_PAGINATION_OFFSET = 2**31 - 1


def describe_database_url(url):
    try:
        parsed = make_url(url)
        host = parsed.host or 'local'
        port = f':{parsed.port}' if parsed.port else ''
        return f'{parsed.get_backend_name()}://{host}{port}/{parsed.database or ""}'
    except Exception:
        return 'unparseable database URL'


def _json_body():
    if not request.is_json:
        return None
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _require_body():
    data = _json_body()
    if data is None:
        return None, (jsonify({'error': 'Invalid request body'}), 400)
    return data, None


def _valid_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None
    return value


def _valid_month(value):
    if not isinstance(value, str) or not MONTH_RE.match(value):
        return None
    try:
        datetime.strptime(value, '%Y-%m')
    except ValueError:
        return None
    return value


def _valid_expense_type(value):
    if not isinstance(value, str) or value not in VALID_EXPENSE_TYPES:
        return None
    return value


def _as_float(value):
    if value is None:
        return 0.0
    return float(value)


def _valid_amount(value):
    if isinstance(value, bool):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount) or amount < 0 or amount > MAX_MONETARY_AMOUNT:
        return None
    return round(amount, 2)


def _resolve_amount(raw, job, present):
    if present and raw is None:
        return None, 'Invalid amount value'
    if not present or (isinstance(raw, str) and raw.strip() == ''):
        raw = 0
    parsed = _valid_amount(raw)
    if parsed is None:
        return None, 'Invalid amount value'
    if parsed == 0:
        parsed = round(_as_float(job.hourly_rate) * _as_float(job.hours_per_day), 2)
        if not math.isfinite(parsed) or parsed < 0 or parsed > MAX_MONETARY_AMOUNT:
            return None, 'Invalid amount value'
    return parsed, None


def _month_bounds(month_str):
    year, month = map(int, month_str.split('-'))
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end


def _parse_pagination(max_limit=500):
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    limit = None
    offset = None

    if raw_limit is not None and raw_limit != '':
        try:
            limit = int(raw_limit)
        except ValueError:
            return None, None, (jsonify({'error': f'limit must be an integer between 1 and {max_limit}'}), 400)
        if limit < 1 or limit > max_limit:
            return None, None, (jsonify({'error': f'limit must be an integer between 1 and {max_limit}'}), 400)

    if raw_offset is not None and raw_offset != '':
        try:
            offset = int(raw_offset)
        except ValueError:
            return None, None, (jsonify({'error': 'offset must be a non-negative integer'}), 400)
        if offset < 0 or offset > MAX_PAGINATION_OFFSET:
            return None, None, (jsonify({'error': f'offset must be between 0 and {MAX_PAGINATION_OFFSET}'}), 400)

    return limit, offset, None


def _clean_str(value, max_len, default=''):
    if value is None:
        return default
    if not isinstance(value, str):
        return default
    value = value.strip()
    if len(value) > max_len:
        return None
    return value


def _clean_tags(value):
    if isinstance(value, list):
        parts = [str(t).strip() for t in value if isinstance(t, (str, int, float))]
    elif isinstance(value, str):
        parts = [t.strip() for t in value.split(',')]
    else:
        parts = []
    tags = []
    for part in parts:
        if not part:
            continue
        part = part[:MAX_TAG_LEN]
        if part:
            tags.append(part)
    return ','.join(tags)[:MAX_TAGS_LEN]


def _clean_color(value):
    if not isinstance(value, str):
        return '#18181b'
    value = value.strip()
    if not value:
        return '#18181b'
    if not COLOR_RE.match(value):
        return '#18181b'
    return value[:MAX_COLOR_LEN]


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_reset_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _validate_credentials(data, min_password_len=1):
    if not isinstance(data, dict):
        return None, None
    username = data.get('username')
    password = data.get('password')
    if not isinstance(username, str) or not isinstance(password, str):
        return None, None
    username = username.strip()
    if not username or len(username) > MAX_USERNAME_LEN:
        return None, None
    if len(password) < min_password_len or len(password.encode('utf-8')) > 72:
        return None, None
    return username, password


def _valid_password(password, min_len=6):
    if not isinstance(password, str):
        return False
    return len(password) >= min_len and len(password.encode('utf-8')) <= 72


def _normalize_username(username):
    return normalize_username(username)


def _find_user_by_username(username):
    normalized = _normalize_username(username)
    return User.query.filter_by(username_normalized=normalized).first()


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != 'admin':
            return jsonify({'error': 'Unauthorized'}), 403
        return view(*args, **kwargs)
    return wrapped
