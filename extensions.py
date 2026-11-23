import secrets
from flask_bcrypt import Bcrypt
from flask_login import LoginManager

bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'

_dummy_password_hash = None


def get_dummy_password_hash():
    global _dummy_password_hash
    if _dummy_password_hash is None:
        _dummy_password_hash = bcrypt.generate_password_hash(secrets.token_hex(8)).decode('utf-8')
    return _dummy_password_hash
