# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "flask==3.0.0",
#     "flask-bcrypt==1.0.1",
#     "flask-login==0.6.3",
#     "flask-sqlalchemy==3.1.1",
#     "gunicorn==21.2.0",
#     "psycopg2-binary==2.9.11",
#     "python-dotenv==1.0.0",
# ]
# ///
import os
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from models import db, User, Job, IncomeRecord, Target, Note, Expense
from datetime import datetime, timedelta
from sqlalchemy import text
import time

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
database_url = os.getenv('DATABASE_URL', 'postgresql://postgres:NRxQKkDqxjjyUaIShsCTEgmMRqDuJEMY@turntable.proxy.rlwy.net:27386/railway')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


def init_db_with_retry(app, retries=5, delay=3):
    for attempt in range(retries):
        try:
            with app.app_context():
                db.create_all()
                db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                if 'postgresql' in db_uri:
                    result = db.session.execute(text("""
                        SELECT table_name FROM information_schema.tables 
                        WHERE table_schema = 'public'
                    """))
                    tables = [row[0] for row in result]
                    required_tables = {'user', 'job', 'income_record', 'target', 'note', 'expense'}
                    existing = set(tables)
                    missing = required_tables - existing
                    if missing:
                        raise RuntimeError(f"Database initialization failed. Missing tables: {missing}")
                    result = db.session.execute(text("""
                        SELECT column_name FROM information_schema.columns 
                        WHERE table_name = 'target' AND column_name = 'work_days_per_week'
                    """))
                    if result.fetchone() is None:
                        db.session.execute(text("ALTER TABLE target ADD COLUMN work_days_per_week FLOAT"))
                        db.session.commit()
                        print("Added work_days_per_week column.")
                elif 'sqlite' in db_uri:
                    result = db.session.execute(text("PRAGMA table_list"))
                    tables = [row[1] for row in result]
                    required_tables = {'user', 'job', 'income_record', 'target', 'note', 'expense'}
                    existing = set(tables)
                    missing = required_tables - existing
                    if missing:
                        raise RuntimeError(f"Database initialization failed. Missing tables: {missing}")
                    result = db.session.execute(text("PRAGMA table_info(target)"))
                    columns = [row[1] for row in result]
                    if 'work_days_per_week' not in columns:
                        db.session.execute(text("ALTER TABLE target ADD COLUMN work_days_per_week FLOAT"))
                        db.session.commit()
                        print("Added work_days_per_week column.")
                db.session.execute(text('SELECT 1'))
                print("Database initialized successfully.")
                return
        except Exception as e:
            print(f"DB not ready (attempt {attempt+1}/{retries}): {e}")
            time.sleep(delay)
    raise RuntimeError("Could not connect to the database after retries.")

init_db_with_retry(app)
# with app.app_context():
#     db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Auth Routes ---

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username already exists'}), 400
    
    hashed_pw = bcrypt.generate_password_hash(data['password']).decode('utf-8')
    new_user = User(username=data['username'], password_hash=hashed_pw)
    
    # First user is admin
    if User.query.count() == 0:
        new_user.role = 'admin'
        
    db.session.add(new_user)
    db.session.commit()
    return jsonify({'message': 'User created successfully'}), 201

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if user and bcrypt.check_password_hash(user.password_hash, data['password']):
        login_user(user)
        return jsonify({
            'id': user.id,
            'username': user.username,
            'role': user.role
        })
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/auth/logout')
@login_required
def logout():
    logout_user()
    return jsonify({'message': 'Logged out'})

@app.route('/api/auth/me')
def me():
    if current_user.is_authenticated:
        return jsonify({
            'id': current_user.id,
            'username': current_user.username,
            'role': current_user.role
        })
    return jsonify(None)

# --- Job Routes ---

@app.route('/api/jobs', methods=['GET', 'POST'])
@login_required
def manage_jobs():
    if request.method == 'POST':
        data = request.json
        try:
            hourly_rate = float(data.get('hourly_rate', 0) or 0)
            hours_per_day = float(data.get('hours_per_day', 0) or 0)
        except ValueError:
            return jsonify({'error': 'Invalid numeric values for rate or hours'}), 400

        new_job = Job(
            name=data['name'],
            hourly_rate=hourly_rate,
            hours_per_day=hours_per_day,
            color=data.get('color', '#18181b'),
            user_id=current_user.id
        )
        db.session.add(new_job)
        db.session.commit()
        return jsonify({
            'id': new_job.id,
            'name': new_job.name,
            'hourly_rate': new_job.hourly_rate,
            'hours_per_day': new_job.hours_per_day,
            'color': new_job.color
        }), 201
    
    jobs = Job.query.filter_by(user_id=current_user.id).all()
    return jsonify([{
        'id': j.id,
        'name': j.name,
        'hourly_rate': j.hourly_rate,
        'hours_per_day': j.hours_per_day,
        'color': j.color
    } for j in jobs])

@app.route('/api/jobs/<int:job_id>', methods=['PUT', 'DELETE'])
@login_required
def manage_job_item(job_id):
    job = Job.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    
    if request.method == 'PUT':
        data = request.json
        job.name = data.get('name', job.name)
        try:
            if 'hourly_rate' in data:
                job.hourly_rate = float(data['hourly_rate'] or 0)
            if 'hours_per_day' in data:
                job.hours_per_day = float(data['hours_per_day'] or 0)
        except ValueError:
            return jsonify({'error': 'Invalid numeric values for rate or hours'}), 400
        job.color = data.get('color', job.color)
        db.session.commit()
        return jsonify({
            'id': job.id,
            'name': job.name,
            'hourly_rate': job.hourly_rate,
            'hours_per_day': job.hours_per_day,
            'color': job.color
        })

    db.session.delete(job)
    db.session.commit()
    return jsonify({'message': 'Job deleted'})

# --- Income Routes ---

@app.route('/api/income', methods=['GET', 'POST'])
@login_required
def manage_income():
    if request.method == 'POST':
        data = request.json
        job = Job.query.get(data['job_id'])
        
        if not job:
            return jsonify({'error': 'Job not found'}), 400
        
        amount = data.get('amount')
        try:
            if amount is None or amount == '' or float(amount) == 0:
                amount = job.hourly_rate * job.hours_per_day
            else:
                amount = float(amount)
        except ValueError:
            return jsonify({'error': 'Invalid amount value'}), 400

        new_record = IncomeRecord(
            job_id=data['job_id'],
            user_id=current_user.id,
            date=data['date'],
            amount=amount,
            job_name=job.name
        )
        db.session.add(new_record)
        db.session.commit()
        return jsonify({
            'id': new_record.id,
            'job_id': new_record.job_id,
            'date': new_record.date,
            'amount': new_record.amount,
            'job_name': new_record.job_name
        }), 201
    
    records = IncomeRecord.query.filter_by(user_id=current_user.id).all()
    return jsonify([{
        'id': r.id,
        'job_id': r.job_id,
        'date': r.date,
        'amount': r.amount,
        'job_name': r.job_name
    } for r in records])

@app.route('/api/income/<int:record_id>', methods=['DELETE'])
@login_required
def delete_income(record_id):
    record = IncomeRecord.query.filter_by(id=record_id, user_id=current_user.id).first_or_404()
    db.session.delete(record)
    db.session.commit()
    return jsonify({'message': 'Record deleted'})

# --- Target Routes ---

@app.route('/api/targets', methods=['GET', 'POST'])
@login_required
def manage_targets():
    if request.method == 'POST':
        data = request.json
        target = Target.query.filter_by(user_id=current_user.id, month=data['month']).first()
        work_days = data.get('work_days_per_week')
        if work_days is not None:
            try:
                work_days = float(work_days)
            except (ValueError, TypeError):
                work_days = None
        if target:
            target.amount = data['amount']
            if work_days is not None:
                target.work_days_per_week = work_days
        else:
            target = Target(
                user_id=current_user.id,
                month=data['month'],
                amount=data['amount'],
                work_days_per_week=work_days
            )
            db.session.add(target)
        db.session.commit()
        return jsonify({
            'id': target.id,
            'month': target.month,
            'amount': target.amount,
            'work_days_per_week': target.work_days_per_week
        })
    
    targets = Target.query.filter_by(user_id=current_user.id).all()
    return jsonify([{
        'id': t.id,
        'month': t.month,
        'amount': t.amount,
        'work_days_per_week': t.work_days_per_week
    } for t in targets])

# --- Admin Routes ---

@app.route('/api/admin/users')
@login_required
def admin_users():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    users = User.query.all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'role': u.role
    } for u in users])

@app.route('/api/admin/users/<int:user_id>', methods=['PUT', 'DELETE'])
@login_required
def admin_manage_user(user_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    user = User.query.get_or_404(user_id)
    
    if request.method == 'PUT':
        data = request.json
        if 'role' in data:
            new_role = data['role']
            if new_role == 'admin' and user.role != 'admin':
                if User.query.filter_by(role='admin').count() >= 1:
                    return jsonify({'error': 'Only one admin user is allowed'}), 400
            if new_role != 'admin' and user.role == 'admin':
                if User.query.filter_by(role='admin').count() <= 1:
                    return jsonify({'error': 'Cannot remove the last admin'}), 400
            user.role = new_role
        db.session.commit()
        return jsonify({'id': user.id, 'username': user.username, 'role': user.role})

    if user.role == 'admin' and User.query.filter_by(role='admin').count() <= 1:
        return jsonify({'error': 'Cannot delete the last admin'}), 400
    
    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'User deleted'})

@app.route('/api/admin/stats')
@login_required
def admin_stats():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    total_users = User.query.count()
    total_jobs = Job.query.count()
    total_records = IncomeRecord.query.count()
    total_income = db.session.query(db.func.sum(IncomeRecord.amount)).scalar() or 0
    
    recent_records = IncomeRecord.query.order_by(IncomeRecord.created_at.desc()).limit(10).all()
    
    return jsonify({
        'total_users': total_users,
        'total_jobs': total_jobs,
        'total_records': total_records,
        'total_income': total_income,
        'recent_activity': [{
            'id': r.id,
            'amount': r.amount,
            'date': r.date,
            'job_name': r.job_name,
            'username': r.user.username if r.user else 'Unknown'
        } for r in recent_records]
    })


# Personal Note Page Router
@app.route('/notes')
@login_required
def notes_page():
    return render_template('note.html')


# --- Note Routes ---
@app.route('/api/notes', methods=['GET', 'POST'])
@login_required
def manage_notes():
    if request.method == 'POST':
        data = request.json
        note = Note(
            user_id=current_user.id,
            title=data.get('title', 'Untitled'),
            content=data.get('content', ''),
            pinned=data.get('pinned', False)
        )
        db.session.add(note)
        db.session.commit()
        return jsonify({
            'id': note.id,
            'title': note.title,
            'content': note.content,
            'pinned': note.pinned,
            'created_at': note.created_at.isoformat(),
            'updated_at': note.updated_at.isoformat()
        }), 201
 
    notes = Note.query.filter_by(user_id=current_user.id)\
        .order_by(Note.pinned.desc(), Note.updated_at.desc()).all()
    return jsonify([{
        'id': n.id,
        'title': n.title,
        'content': n.content,
        'pinned': n.pinned,
        'created_at': n.created_at.isoformat(),
        'updated_at': n.updated_at.isoformat()
    } for n in notes])
 
 
@app.route('/api/notes/<int:note_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def manage_note_item(note_id):
    note = Note.query.filter_by(id=note_id, user_id=current_user.id).first_or_404()
 
    if request.method == 'GET':
        return jsonify({
            'id': note.id,
            'title': note.title,
            'content': note.content,
            'pinned': note.pinned,
            'created_at': note.created_at.isoformat(),
            'updated_at': note.updated_at.isoformat()
        })
 
    if request.method == 'PUT':
        data = request.json
        if 'title' in data:
            note.title = data['title']
        if 'content' in data:
            note.content = data['content']
        if 'pinned' in data:
            note.pinned = data['pinned']
        note.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({
            'id': note.id,
            'title': note.title,
            'content': note.content,
            'pinned': note.pinned,
            'created_at': note.created_at.isoformat(),
            'updated_at': note.updated_at.isoformat()
        })
 
    db.session.delete(note)
    db.session.commit()
    return jsonify({'message': 'Note deleted'})

# --- Expense Routes ---

@app.route('/api/expenses', methods=['GET', 'POST'])
@login_required
def manage_expenses():
    if request.method == 'POST':
        data = request.json
        try:
            amount = float(data.get('amount', 0))
        except ValueError:
            return jsonify({'error': 'Invalid amount'}), 400

        tags_raw = data.get('tags', [])
        tags_str = ','.join([t.strip() for t in tags_raw if t.strip()]) if isinstance(tags_raw, list) else data.get('tags', '')

        expense = Expense(
            user_id=current_user.id,
            date=data['date'],
            amount=amount,
            description=data.get('description', ''),
            tags=tags_str,
            expense_type=data.get('expense_type', 'daily')
        )
        db.session.add(expense)
        db.session.commit()
        return jsonify({
            'id': expense.id,
            'date': expense.date,
            'amount': expense.amount,
            'description': expense.description,
            'tags': expense.tags.split(',') if expense.tags else [],
            'expense_type': expense.expense_type,
            'created_at': expense.created_at.isoformat()
        }), 201

    expenses = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.date.desc()).all()
    return jsonify([{
        'id': e.id,
        'date': e.date,
        'amount': e.amount,
        'description': e.description,
        'tags': e.tags.split(',') if e.tags else [],
        'expense_type': e.expense_type,
        'created_at': e.created_at.isoformat()
    } for e in expenses])


@app.route('/api/expenses/<int:expense_id>', methods=['PUT', 'DELETE'])
@login_required
def manage_expense_item(expense_id):
    expense = Expense.query.filter_by(id=expense_id, user_id=current_user.id).first_or_404()

    if request.method == 'PUT':
        data = request.json
        if 'amount' in data:
            try:
                expense.amount = float(data['amount'])
            except ValueError:
                return jsonify({'error': 'Invalid amount'}), 400
        if 'description' in data:
            expense.description = data['description']
        if 'date' in data:
            expense.date = data['date']
        if 'tags' in data:
            tags_raw = data['tags']
            expense.tags = ','.join([t.strip() for t in tags_raw if t.strip()]) if isinstance(tags_raw, list) else tags_raw
        if 'expense_type' in data:
            expense.expense_type = data['expense_type']
        db.session.commit()
        return jsonify({
            'id': expense.id,
            'date': expense.date,
            'amount': expense.amount,
            'description': expense.description,
            'tags': expense.tags.split(',') if expense.tags else [],
            'expense_type': expense.expense_type
        })

    db.session.delete(expense)
    db.session.commit()
    return jsonify({'message': 'Expense deleted'})


@app.route('/api/expenses/stats')
@login_required
def expense_stats():
    from sqlalchemy import func
    expenses = Expense.query.filter_by(user_id=current_user.id).all()
    current_month = datetime.utcnow().strftime('%Y-%m')

    monthly = [e for e in expenses if e.date.startswith(current_month)]
    monthly_total = sum(e.amount for e in monthly)

    by_type = {}
    for e in monthly:
        by_type[e.expense_type] = by_type.get(e.expense_type, 0) + e.amount

    all_tags = {}
    for e in monthly:
        for tag in (e.tags.split(',') if e.tags else []):
            tag = tag.strip()
            if tag:
                all_tags[tag] = all_tags.get(tag, 0) + e.amount

    return jsonify({
        'monthly_total': monthly_total,
        'by_type': by_type,
        'by_tag': all_tags
    })


@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=False)