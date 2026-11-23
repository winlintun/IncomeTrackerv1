from collections import deque
from functools import wraps
import hmac
import math
import secrets
import threading
import time
from flask import current_app, jsonify, make_response, request, session

CSRF_HEADER = 'X-CSRF-Token'
CSRF_SESSION_KEY = '_csrf_token'
MUTATING_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}


def get_csrf_token():
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_hex(32)
        session[CSRF_SESSION_KEY] = token
    return token


def clear_csrf_token():
    session.pop(CSRF_SESSION_KEY, None)


def validate_csrf_request():
    if request.method not in MUTATING_METHODS:
        return None
    if not request.path.startswith('/api/'):
        return None
    if not current_app.config.get('WTF_CSRF_ENABLED', True):
        return None
    expected = session.get(CSRF_SESSION_KEY)
    provided = request.headers.get(CSRF_HEADER)
    if not provided and request.is_json:
        body = request.get_json(silent=True)
        if isinstance(body, dict) and isinstance(body.get('csrf_token'), str):
            provided = body.get('csrf_token')
    if not expected or not isinstance(provided, str) or not hmac.compare_digest(expected, provided):
        return jsonify({'error': 'Invalid or missing CSRF token'}), 403
    return None


class RateLimiter:
    def __init__(self, max_keys=1024):
        self._buckets = {}
        self._max_keys = max_keys
        self._lock = threading.Lock()

    def reset(self):
        with self._lock:
            self._buckets.clear()

    def _prune_stale(self, now):
        stale_keys = []
        for k, (bucket, win) in self._buckets.items():
            cutoff = now - win
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                stale_keys.append(k)
        for k in stale_keys:
            del self._buckets[k]

    def check(self, key, limit, window_seconds):
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            if len(self._buckets) >= self._max_keys:
                self._prune_stale(now)
                if len(self._buckets) >= self._max_keys and key not in self._buckets:
                    oldest_key = next(iter(self._buckets))
                    del self._buckets[oldest_key]
            entry = self._buckets.get(key)
            if entry is None:
                bucket = deque()
                self._buckets[key] = (bucket, window_seconds)
            else:
                bucket, _ = entry
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if not bucket:
                    self._buckets[key] = (bucket, window_seconds)
            if len(bucket) >= limit:
                retry_after = max(1, int(math.ceil(bucket[0] + window_seconds - now)))
                return False, 0, retry_after
            bucket.append(now)
            return True, limit - len(bucket), 0


rate_limiter = RateLimiter()


def _client_ip():
    return request.remote_addr or '127.0.0.1'


def rate_limit(max_requests, window_seconds, key_prefix=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            enabled = current_app.config.get('RATELIMIT_ENABLED', not current_app.config.get('TESTING', False))
            if not enabled:
                return view(*args, **kwargs)
            prefix = key_prefix or request.endpoint or view.__name__
            key = f'{prefix}:{_client_ip()}'
            allowed, remaining, retry_after = rate_limiter.check(key, max_requests, window_seconds)
            if not allowed:
                response = make_response(jsonify({'error': 'Too many requests. Please try again later.'}), 429)
                response.headers['Retry-After'] = str(retry_after)
                response.headers['X-RateLimit-Limit'] = str(max_requests)
                response.headers['X-RateLimit-Remaining'] = '0'
                return response
            response = make_response(view(*args, **kwargs))
            response.headers['X-RateLimit-Limit'] = str(max_requests)
            response.headers['X-RateLimit-Remaining'] = str(remaining)
            return response
        return wrapped
    return decorator
