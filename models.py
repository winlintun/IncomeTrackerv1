from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timezone
import unicodedata
from sqlalchemy.orm import validates


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


MAX_USERNAME_LEN = 80


def normalize_username(username):
    """Case-insensitive lookup key: NFKC, casefold, then fit the column.

    Truncating here keeps the key inside VARCHAR(80) on PostgreSQL even when NFKC
    or casefold expands a character (e.g. the 'ﬁ' ligature becomes 'fi'), and keeps
    registration, migration and login computing the same value.
    """
    normalized = unicodedata.normalize('NFKC', username).casefold()
    return normalized[:MAX_USERNAME_LEN]


db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    username_normalized = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='user')
    jobs = db.relationship('Job', backref='owner', lazy=True, cascade="all, delete-orphan")
    income_records = db.relationship('IncomeRecord', backref='user', lazy=True, cascade="all, delete-orphan")
    targets = db.relationship('Target', backref='user', lazy=True, cascade="all, delete-orphan")
    expenses = db.relationship('Expense', backref='user', lazy=True, cascade="all, delete-orphan")
    expense_budgets = db.relationship('ExpenseBudget', backref='user', lazy=True, cascade="all, delete-orphan")
    notes = db.relationship('Note', backref='user', lazy=True, cascade="all, delete-orphan")
    password_reset_tokens = db.relationship('PasswordResetToken', backref='user', lazy=True,
                                            cascade="all, delete-orphan")

    @validates('username')
    def _sync_normalized_username(self, key, value):
        self.username_normalized = normalize_username(value)
        return value

class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    hourly_rate = db.Column(db.Numeric(12, 2, asdecimal=False), nullable=False)
    hours_per_day = db.Column(db.Float, nullable=False)
    color = db.Column(db.String(20), default='#18181b') # Default zinc-900
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    income_records = db.relationship('IncomeRecord', backref='job', lazy=True, cascade="all, delete-orphan")

class IncomeRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(10), nullable=False)  # YYYY-MM-DD
    amount = db.Column(db.Numeric(12, 2, asdecimal=False), nullable=False)
    job_name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=utcnow)

class Target(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    month = db.Column(db.String(7), nullable=False)  # YYYY-MM
    amount = db.Column(db.Numeric(12, 2, asdecimal=False), nullable=False)
    work_days_per_week = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'month', name='uq_target_user_month'),
    )


class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False, default='')
    pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(10), nullable=False)       # YYYY-MM-DD
    amount = db.Column(db.Numeric(12, 2, asdecimal=False), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    tags = db.Column(db.String(500), default='')           # comma-separated tags
    expense_type = db.Column(db.String(50), default='daily')  # daily / bills / work / one-time
    created_at = db.Column(db.DateTime, default=utcnow)


class ExpenseBudget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    month = db.Column(db.String(7), nullable=False)  # YYYY-MM
    expense_type = db.Column(db.String(50), nullable=False)  # daily / bills / work / one-time
    limit_amount = db.Column(db.Numeric(12, 2, asdecimal=False), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'month', 'expense_type', name='uq_expense_budget_user_month_type'),
    )


class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    value = db.Column(db.String(200), nullable=False, default='')
