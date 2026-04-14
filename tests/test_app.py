import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app as flask_app, bcrypt
from models import db, User, Job, IncomeRecord, Target, Note, Expense


@pytest.fixture
def app():
    flask_app.config['TESTING'] = True
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    flask_app.config['WTF_CSRF_ENABLED'] = False
    flask_app.config['SECRET_KEY'] = 'test-secret'
    
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(app, client):
    with app.app_context():
        hashed = bcrypt.generate_password_hash('testpass').decode('utf-8')
        user = User(username='testuser', password_hash=hashed, role='user')
        db.session.add(user)
        db.session.commit()
    
    client.post('/api/auth/login', json={'username': 'testuser', 'password': 'testpass'})
    return client


@pytest.fixture
def admin_client(app, client):
    with app.app_context():
        hashed = bcrypt.generate_password_hash('adminpass').decode('utf-8')
        user = User(username='admin', password_hash=hashed, role='admin')
        db.session.add(user)
        db.session.commit()
    
    client.post('/api/auth/login', json={'username': 'admin', 'password': 'adminpass'})
    return client


@pytest.fixture
def sample_job(app, auth_client):
    response = auth_client.post('/api/jobs', json={
        'name': 'Test Job',
        'hourly_rate': 200,
        'hours_per_day': 8,
        'color': '#18181b'
    })
    return response.get_json()


class TestAuth:
    def test_register_success(self, client):
        response = client.post('/api/auth/register', json={
            'username': 'newuser',
            'password': 'password123'
        })
        assert response.status_code == 201
        assert response.get_json()['message'] == 'User created successfully'
    
    def test_register_duplicate_username(self, client):
        client.post('/api/auth/register', json={'username': 'testuser', 'password': 'pass'})
        response = client.post('/api/auth/register', json={
            'username': 'testuser',
            'password': 'pass2'
        })
        assert response.status_code == 400
        assert 'Username already exists' in response.get_json()['error']
    
    def test_first_user_is_admin(self, client):
        response = client.post('/api/auth/register', json={
            'username': 'first',
            'password': 'pass'
        })
        assert response.status_code == 201
        with flask_app.app_context():
            user = User.query.filter_by(username='first').first()
            assert user.role == 'admin'
    
    def test_login_success(self, client):
        client.post('/api/auth/register', json={'username': 'user1', 'password': 'pass'})
        response = client.post('/api/auth/login', json={
            'username': 'user1',
            'password': 'pass'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['username'] == 'user1'
    
    def test_login_invalid_credentials(self, client):
        client.post('/api/auth/register', json={'username': 'user2', 'password': 'pass'})
        response = client.post('/api/auth/login', json={
            'username': 'user2',
            'password': 'wrongpass'
        })
        assert response.status_code == 401
    
    def test_logout(self, auth_client):
        response = auth_client.get('/api/auth/logout')
        assert response.status_code == 200
        assert response.get_json()['message'] == 'Logged out'
    
    def test_me_authenticated(self, auth_client):
        response = auth_client.get('/api/auth/me')
        assert response.status_code == 200
        assert response.get_json()['username'] == 'testuser'
    
    def test_me_unauthenticated(self, client):
        response = client.get('/api/auth/me')
        assert response.status_code == 200
        assert response.get_json() is None


class TestJobs:
    def test_create_job(self, auth_client):
        response = auth_client.post('/api/jobs', json={
            'name': 'Freelance',
            'hourly_rate': 300,
            'hours_per_day': 6,
            'color': '#10b981'
        })
        assert response.status_code == 201
        data = response.get_json()
        assert data['name'] == 'Freelance'
        assert data['hourly_rate'] == 300.0
    
    def test_create_job_invalid_rate(self, auth_client):
        response = auth_client.post('/api/jobs', json={
            'name': 'Job',
            'hourly_rate': 'invalid',
            'hours_per_day': 8
        })
        assert response.status_code == 400
    
    def test_get_jobs(self, auth_client, sample_job):
        response = auth_client.get('/api/jobs')
        assert response.status_code == 200
        jobs = response.get_json()
        assert len(jobs) >= 1
    
    def test_update_job(self, auth_client, sample_job):
        job_id = sample_job['id']
        response = auth_client.put(f'/api/jobs/{job_id}', json={
            'name': 'Updated Job',
            'hourly_rate': 250
        })
        assert response.status_code == 200
        assert response.get_json()['name'] == 'Updated Job'
        assert response.get_json()['hourly_rate'] == 250.0
    
    def test_delete_job(self, auth_client, sample_job):
        job_id = sample_job['id']
        response = auth_client.delete(f'/api/jobs/{job_id}')
        assert response.status_code == 200
        assert response.get_json()['message'] == 'Job deleted'
    
    def test_jobs_isolated_by_user(self, client):
        client.post('/api/auth/register', json={'username': 'user1', 'password': 'pass'})
        client.post('/api/auth/login', json={'username': 'user1', 'password': 'pass'})
        client.post('/api/jobs', json={
            'name': 'User1 Job',
            'hourly_rate': 100,
            'hours_per_day': 8,
            'color': '#18181b'
        })
        
        client.post('/api/auth/register', json={'username': 'user2', 'password': 'pass'})
        client.post('/api/auth/login', json={'username': 'user2', 'password': 'pass'})
        response = client.get('/api/jobs')
        jobs = response.get_json()
        assert all(j['name'] != 'User1 Job' for j in jobs)


class TestIncome:
    def test_create_income_auto_amount(self, auth_client, sample_job):
        response = auth_client.post('/api/income', json={
            'job_id': sample_job['id'],
            'date': '2026-04-09',
            'amount': 0
        })
        assert response.status_code == 201
        data = response.get_json()
        assert data['amount'] == 1600.0
    
    def test_create_income_manual_amount(self, auth_client, sample_job):
        response = auth_client.post('/api/income', json={
            'job_id': sample_job['id'],
            'date': '2026-04-09',
            'amount': 500
        })
        assert response.status_code == 201
        assert response.get_json()['amount'] == 500.0
    
    def test_create_income_invalid_job(self, auth_client):
        response = auth_client.post('/api/income', json={
            'job_id': 9999,
            'date': '2026-04-09',
            'amount': 100
        })
        assert response.status_code == 400
        assert 'Job not found' in response.get_json()['error']
    
    def test_create_income_invalid_amount(self, auth_client, sample_job):
        response = auth_client.post('/api/income', json={
            'job_id': sample_job['id'],
            'date': '2026-04-09',
            'amount': 'invalid'
        })
        assert response.status_code == 400
    
    def test_get_income(self, auth_client, sample_job):
        auth_client.post('/api/income', json={
            'job_id': sample_job['id'],
            'date': '2026-04-09',
            'amount': 100
        })
        response = auth_client.get('/api/income')
        assert response.status_code == 200
        assert len(response.get_json()) >= 1
    
    def test_delete_income(self, auth_client, sample_job):
        create_response = auth_client.post('/api/income', json={
            'job_id': sample_job['id'],
            'date': '2026-04-09',
            'amount': 100
        })
        record_id = create_response.get_json()['id']
        response = auth_client.delete(f'/api/income/{record_id}')
        assert response.status_code == 200

    def test_update_income(self, auth_client, sample_job):
        create_response = auth_client.post('/api/income', json={
            'job_id': sample_job['id'],
            'date': '2026-04-09',
            'amount': 100
        })
        record_id = create_response.get_json()['id']
        response = auth_client.put(f'/api/income/{record_id}', json={
            'job_id': sample_job['id'],
            'date': '2026-04-15',
            'amount': 200
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['amount'] == 200.0
        assert data['date'] == '2026-04-15'


class TestTargets:
    def test_create_target(self, auth_client):
        response = auth_client.post('/api/targets', json={
            'month': '2026-04',
            'amount': 50000,
            'work_days_per_week': 5
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['amount'] == 50000
        assert data['work_days_per_week'] == 5.0
    
    def test_update_existing_target(self, auth_client):
        auth_client.post('/api/targets', json={'month': '2026-04', 'amount': 40000})
        response = auth_client.post('/api/targets', json={
            'month': '2026-04',
            'amount': 60000,
            'work_days_per_week': 6
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['amount'] == 60000
        assert data['work_days_per_week'] == 6.0
    
    def test_get_targets(self, auth_client):
        auth_client.post('/api/targets', json={'month': '2026-04', 'amount': 50000})
        response = auth_client.get('/api/targets')
        assert response.status_code == 200
        assert len(response.get_json()) >= 1
    
    def test_target_work_days_optional(self, auth_client):
        response = auth_client.post('/api/targets', json={
            'month': '2026-04',
            'amount': 50000
        })
        assert response.status_code == 200
        assert response.get_json()['work_days_per_week'] is None


class TestNotes:
    def test_create_note(self, auth_client):
        response = auth_client.post('/api/notes', json={
            'title': 'Test Note',
            'content': 'Note content here',
            'pinned': False
        })
        assert response.status_code == 201
        data = response.get_json()
        assert data['title'] == 'Test Note'
        assert data['content'] == 'Note content here'
    
    def test_get_notes(self, auth_client):
        auth_client.post('/api/notes', json={'title': 'Note 1', 'content': 'Content'})
        auth_client.post('/api/notes', json={'title': 'Note 2', 'content': 'Content 2', 'pinned': True})
        response = auth_client.get('/api/notes')
        assert response.status_code == 200
        notes = response.get_json()
        assert len(notes) >= 2
        assert notes[0]['pinned'] == True
    
    def test_update_note(self, auth_client):
        create_response = auth_client.post('/api/notes', json={'title': 'Original', 'content': 'Content'})
        note_id = create_response.get_json()['id']
        response = auth_client.put(f'/api/notes/{note_id}', json={
            'title': 'Updated',
            'content': 'New content'
        })
        assert response.status_code == 200
        assert response.get_json()['title'] == 'Updated'
    
    def test_toggle_pin(self, auth_client):
        create_response = auth_client.post('/api/notes', json={'title': 'Note', 'content': 'Content'})
        note_id = create_response.get_json()['id']
        response = auth_client.put(f'/api/notes/{note_id}', json={'pinned': True})
        assert response.status_code == 200
        assert response.get_json()['pinned'] == True
    
    def test_delete_note(self, auth_client):
        create_response = auth_client.post('/api/notes', json={'title': 'To Delete', 'content': 'Content'})
        note_id = create_response.get_json()['id']
        response = auth_client.delete(f'/api/notes/{note_id}')
        assert response.status_code == 200
    
    def test_notes_isolated_by_user(self, client):
        client.post('/api/auth/register', json={'username': 'user1', 'password': 'pass'})
        client.post('/api/auth/login', json={'username': 'user1', 'password': 'pass'})
        client.post('/api/notes', json={'title': 'User1 Private Note', 'content': 'Secret'})
        
        client.post('/api/auth/register', json={'username': 'user2', 'password': 'pass'})
        client.post('/api/auth/login', json={'username': 'user2', 'password': 'pass'})
        response = client.get('/api/notes')
        notes = response.get_json()
        assert all(n['title'] != 'User1 Private Note' for n in notes)


class TestExpenses:
    def test_create_expense(self, auth_client):
        response = auth_client.post('/api/expenses', json={
            'date': '2026-04-09',
            'amount': 150,
            'description': 'Groceries',
            'tags': ['food', 'monthly'],
            'expense_type': 'daily'
        })
        assert response.status_code == 201
        data = response.get_json()
        assert data['amount'] == 150.0
        assert data['tags'] == ['food', 'monthly']
    
    def test_create_expense_invalid_amount(self, auth_client):
        response = auth_client.post('/api/expenses', json={
            'date': '2026-04-09',
            'amount': 'invalid',
            'description': 'Test'
        })
        assert response.status_code == 400
    
    def test_get_expenses(self, auth_client):
        auth_client.post('/api/expenses', json={
            'date': '2026-04-09',
            'amount': 100,
            'description': 'Test'
        })
        response = auth_client.get('/api/expenses')
        assert response.status_code == 200
        assert len(response.get_json()) >= 1
    
    def test_update_expense(self, auth_client):
        create_response = auth_client.post('/api/expenses', json={
            'date': '2026-04-09',
            'amount': 100,
            'description': 'Original'
        })
        expense_id = create_response.get_json()['id']
        response = auth_client.put(f'/api/expenses/{expense_id}', json={
            'amount': 200,
            'tags': ['updated']
        })
        assert response.status_code == 200
        assert response.get_json()['amount'] == 200.0
        assert response.get_json()['tags'] == ['updated']
    
    def test_delete_expense(self, auth_client):
        create_response = auth_client.post('/api/expenses', json={
            'date': '2026-04-09',
            'amount': 100,
            'description': 'To Delete'
        })
        expense_id = create_response.get_json()['id']
        response = auth_client.delete(f'/api/expenses/{expense_id}')
        assert response.status_code == 200
    
    def test_expense_stats(self, auth_client):
        auth_client.post('/api/expenses', json={
            'date': '2026-04-09',
            'amount': 100,
            'description': 'Food',
            'expense_type': 'daily'
        })
        auth_client.post('/api/expenses', json={
            'date': '2026-04-09',
            'amount': 50,
            'description': 'Bill',
            'expense_type': 'bills'
        })
        response = auth_client.get('/api/expenses/stats')
        assert response.status_code == 200
        data = response.get_json()
        assert 'monthly_total' in data
        assert 'by_type' in data


class TestAdmin:
    def test_admin_users_access(self, admin_client):
        response = admin_client.get('/api/admin/users')
        assert response.status_code == 200
        assert isinstance(response.get_json(), list)
    
    def test_admin_stats_access(self, admin_client):
        response = admin_client.get('/api/admin/stats')
        assert response.status_code == 200
        data = response.get_json()
        assert 'total_users' in data
        assert 'total_jobs' in data
    
    def test_non_admin_denied(self, auth_client):
        response = auth_client.get('/api/admin/users')
        assert response.status_code == 403
    
    def test_update_user_role(self, admin_client):
        with flask_app.app_context():
            hashed = bcrypt.generate_password_hash('hashpass').decode('utf-8')
            user = User(username='regular', password_hash=hashed, role='user')
            db.session.add(user)
            db.session.commit()
            user_id = user.id
        
        response = admin_client.put(f'/api/admin/users/{user_id}', json={'role': 'user'})
        assert response.status_code == 200
        assert response.get_json()['role'] == 'user'
    
    def test_cannot_remove_last_admin(self, admin_client):
        with flask_app.app_context():
            admin_user = User.query.filter_by(role='admin').first()
            admin_id = admin_user.id
        
        response = admin_client.delete(f'/api/admin/users/{admin_id}')
        assert response.status_code == 400
        assert 'last admin' in response.get_json()['error'].lower()
    
    def test_only_one_admin(self, admin_client):
        with flask_app.app_context():
            hashed = bcrypt.generate_password_hash('hashpass').decode('utf-8')
            user = User(username='newadmin', password_hash=hashed, role='user')
            db.session.add(user)
            db.session.commit()
            user_id = user.id
        
        response = admin_client.put(f'/api/admin/users/{user_id}', json={'role': 'admin'})
        assert response.status_code == 400
        assert 'one admin' in response.get_json()['error'].lower()


class TestSecurity:
    def test_unauthenticated_job_access(self, client):
        response = client.get('/api/jobs')
        assert response.status_code in [302, 401]
    
    def test_unauthenticated_income_access(self, client):
        response = client.get('/api/income')
        assert response.status_code in [302, 401]
    
    def test_unauthenticated_target_access(self, client):
        response = client.get('/api/targets')
        assert response.status_code in [302, 401]
    
    def test_unauthenticated_notes_access(self, client):
        response = client.get('/api/notes')
        assert response.status_code in [302, 401]
    
    def test_unauthenticated_expenses_access(self, client):
        response = client.get('/api/expenses')
        assert response.status_code in [302, 401]
    
    def test_user_cannot_access_other_user_data(self, auth_client, client):
        auth_client.post('/api/jobs', json={
            'name': 'Private Job',
            'hourly_rate': 100,
            'hours_per_day': 8,
            'color': '#18181b'
        })
        
        client.post('/api/auth/register', json={'username': 'other', 'password': 'pass'})
        client.post('/api/auth/login', json={'username': 'other', 'password': 'pass'})
        response = client.get('/api/jobs')
        jobs = response.get_json()
        assert all(j['name'] != 'Private Job' for j in jobs)


class TestNotesPage:
    def test_notes_page_accessible(self, auth_client):
        response = auth_client.get('/notes')
        assert response.status_code == 200
        assert b'Notes' in response.data


class TestDashboard:
    def test_dashboard_accessible(self, client):
        response = client.get('/')
        assert response.status_code == 200
        assert b'IncomeTracker' in response.data
