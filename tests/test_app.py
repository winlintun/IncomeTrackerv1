import pytest
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DB = 'sqlite://'
os.environ['DATABASE_URL'] = TEST_DB
os.environ.setdefault('FLASK_ENV', 'development')

from app import app as flask_app, bcrypt
from models import db, User, Job, IncomeRecord, Target, Note, Expense


@pytest.fixture
def app():
    with flask_app.app_context():
        url = str(db.engine.url)
        if 'postgresql' in url or url != TEST_DB:
            raise RuntimeError(f'Refusing to run tests against non-test database: {url}')
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    flask_app.config['SECRET_KEY'] = 'test-secret'

    with flask_app.app_context():
        db.drop_all()
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
        mark_bootstrap_done()
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


def mark_bootstrap_done():
    from models import Setting
    if Setting.query.filter_by(key='admin_bootstrap_done').first() is None:
        db.session.add(Setting(key='admin_bootstrap_done', value='1'))


def issue_reset_token(app, username='alice'):
    """Request a reset as an isolated admin client so the plaintext token comes back."""
    with app.app_context():
        hashed = bcrypt.generate_password_hash('adminpass').decode('utf-8')
        admin = User(username='resetter', password_hash=hashed, role='admin')
        db.session.add(admin)
        mark_bootstrap_done()
        db.session.commit()
    admin_client = app.test_client()
    admin_client.post('/api/auth/login', json={'username': 'resetter', 'password': 'adminpass'})
    response = admin_client.post('/api/auth/forgot-password', json={'username': username})
    return response.get_json()['reset_token']


class TestAuthHardening:
    def test_register_missing_fields_400(self, client):
        assert client.post('/api/auth/register', json={}).status_code == 400
        assert client.post('/api/auth/register', json={'username': 'x'}).status_code == 400

    def test_register_nonstring_username_400(self, client):
        assert client.post('/api/auth/register', json={'username': 123, 'password': 'abc'}).status_code == 400
        assert client.post('/api/auth/register', json={'username': True, 'password': 'abc'}).status_code == 400
        assert client.post('/api/auth/register', json={'username': ['a'], 'password': 'abc'}).status_code == 400

    def test_login_nonstring_username_401(self, client):
        assert client.post('/api/auth/login', json={'username': 123, 'password': 'abc'}).status_code == 401
        assert client.post('/api/auth/login', json={'username': {'u': 1}, 'password': 'abc'}).status_code == 401

    def test_login_missing_fields_401(self, client):
        response = client.post('/api/auth/login', json={})
        assert response.status_code == 401
        assert response.get_json()['error'] == 'Invalid credentials'

    def test_register_long_password_rejected(self, client):
        response = client.post('/api/auth/register', json={'username': 'toolong', 'password': 'a' * 100})
        assert response.status_code == 400

    def test_register_short_password_rejected(self, client):
        response = client.post('/api/auth/register', json={'username': 'shortpass', 'password': 'abc1'})
        assert response.status_code == 400
        assert '6 to 72 bytes' in response.get_json()['error']

    def test_login_long_password_401_not_500(self, client):
        with flask_app.app_context():
            hashed = bcrypt.generate_password_hash('normalpass').decode('utf-8')
            db.session.add(User(username='short', password_hash=hashed))
            db.session.commit()
        response = client.post('/api/auth/login', json={'username': 'short', 'password': 'a' * 100})
        assert response.status_code == 401

    def test_unauthenticated_api_returns_401_json(self, client):
        response = client.get('/api/jobs')
        assert response.status_code == 401
        assert response.get_json()['error'] == 'Authentication required'

    def test_unauthenticated_page_redirects_home(self, client):
        response = client.get('/notes')
        assert response.status_code == 302
        assert response.headers['Location'].endswith('/')

    def test_db_health_endpoint(self, client):
        response = client.get('/api/health/db')
        assert response.status_code == 200
        body = response.get_json()
        assert body['status'] == 'ok'
        assert 'dialect' not in body
        assert 'target' not in body

    def test_db_health_endpoint_admin_sees_details(self, admin_client):
        response = admin_client.get('/api/health/db')
        assert response.status_code == 200
        body = response.get_json()
        assert body['status'] == 'ok'
        assert body['dialect'] == 'sqlite'

    def test_reset_password_long_password_400(self, client):
        response = client.post('/api/auth/reset-password', json={
            'username': 'anyone', 'token': 'tok', 'new_password': 'a' * 100})
        assert response.status_code == 400

    def test_forgot_password_malformed_bodies_400(self, client):
        assert client.post('/api/auth/forgot-password', json=[1, 2]).status_code == 400
        assert client.post('/api/auth/forgot-password', json={'username': 123}).status_code == 400

    def test_reset_password_malformed_bodies_400(self, client):
        assert client.post('/api/auth/reset-password', json=[1, 2]).status_code == 400
        assert client.post('/api/auth/reset-password', json={'username': 'u', 'token': 123, 'new_password': 'abcdef'}).status_code == 400

    def test_admin_delete_user_with_notes_and_tokens(self, admin_client):
        with flask_app.app_context():
            hashed = bcrypt.generate_password_hash('pass1234').decode('utf-8')
            user = User(username='hasnotes', password_hash=hashed)
            db.session.add(user)
            db.session.commit()
            uid = user.id
            db.session.add(Note(user_id=uid, title='t', content='c'))
            from models import PasswordResetToken
            from datetime import datetime
            db.session.add(PasswordResetToken(user_id=uid, token='tok123', expires_at=datetime(2030, 1, 1)))
            db.session.commit()

        response = admin_client.delete(f'/api/admin/users/{uid}')
        assert response.status_code == 200
        with flask_app.app_context():
            from models import PasswordResetToken
            assert db.session.get(User, uid) is None
            assert PasswordResetToken.query.count() == 0
            assert Note.query.count() == 0


class TestAuth:
    def test_forgot_password_unknown_user(self, client):
        response = client.post('/api/auth/forgot-password', json={'username': 'ghost'})
        assert response.status_code == 200
        body = response.get_json()
        assert 'reset_token' not in body
        with flask_app.app_context():
            from models import PasswordResetToken
            assert PasswordResetToken.query.count() == 0

    def test_forgot_password_creates_token_and_resets(self, client):
        client.post('/api/auth/register', json={'username': 'alice', 'password': 'oldpass'})

        response = client.post('/api/auth/forgot-password', json={'username': 'alice'})
        assert response.status_code == 200
        assert 'reset_token' not in response.get_json()

        with flask_app.app_context():
            from models import PasswordResetToken
            reset = PasswordResetToken.query.first()
            assert reset is not None
            token = reset.token

        response = client.post('/api/auth/reset-password', json={
            'username': 'alice', 'token': token, 'new_password': 'newpass123'
        })
        assert response.status_code == 400

    def test_reset_password_token_is_stored_hashed(self, client, app):
        client.post('/api/auth/register', json={'username': 'alice', 'password': 'pass123'})
        token = issue_reset_token(app, 'alice')
        with flask_app.app_context():
            from models import PasswordResetToken
            stored = PasswordResetToken.query.first().token
            assert stored != token
            assert len(stored) == 64

    def test_reset_password_invalid_token(self, client):
        client.post('/api/auth/register', json={'username': 'alice', 'password': 'pass123'})
        response = client.post('/api/auth/reset-password', json={
            'username': 'alice', 'token': 'bogus', 'new_password': 'newpass123'
        })
        assert response.status_code == 400

    def test_reset_password_token_reuse_rejected(self, client, app):
        client.post('/api/auth/register', json={'username': 'alice', 'password': 'pass123'})
        token = issue_reset_token(app, 'alice')
        client.post('/api/auth/reset-password', json={'username': 'alice', 'token': token, 'new_password': 'newpass1'})
        response = client.post('/api/auth/reset-password', json={'username': 'alice', 'token': token, 'new_password': 'newpass2'})
        assert response.status_code == 400

    def test_reset_password_short_password_rejected(self, client, app):
        client.post('/api/auth/register', json={'username': 'alice', 'password': 'pass123'})
        token = issue_reset_token(app, 'alice')
        response = client.post('/api/auth/reset-password', json={'username': 'alice', 'token': token, 'new_password': 'abc'})
        assert response.status_code == 400

    def test_reset_password_username_mismatch_rejected(self, client, app):
        client.post('/api/auth/register', json={'username': 'alice', 'password': 'pass123'})
        token = issue_reset_token(app, 'alice')
        response = client.post('/api/auth/reset-password', json={'username': 'eve', 'token': token, 'new_password': 'hack123'})
        assert response.status_code == 400

    def test_forgot_password_admin_gets_token_in_response(self, admin_client):
        client = admin_client
        with flask_app.app_context():
            hashed = bcrypt.generate_password_hash('userpass').decode('utf-8')
            user = User(username='bob', password_hash=hashed, role='user')
            db.session.add(user)
            db.session.commit()

        response = client.post('/api/auth/forgot-password', json={'username': 'bob'})
        assert response.status_code == 200
        assert response.get_json()['reset_token']

    def test_forgot_password_non_admin_gets_no_token(self, auth_client):
        response = auth_client.post('/api/auth/forgot-password', json={'username': 'testuser'})
        assert response.status_code == 200
        assert 'reset_token' not in response.get_json()

    def test_forgot_password_expires(self, client, app):
        from datetime import datetime
        client.post('/api/auth/register', json={'username': 'alice', 'password': 'pass123'})
        token = issue_reset_token(app, 'alice')
        with flask_app.app_context():
            from models import PasswordResetToken
            reset = PasswordResetToken.query.first()
            reset.expires_at = datetime(2020, 1, 1)
            db.session.commit()
        response = client.post('/api/auth/reset-password', json={'username': 'alice', 'token': token, 'new_password': 'newpass1'})
        assert response.status_code == 400

    def test_register_success(self, client):
        response = client.post('/api/auth/register', json={
            'username': 'newuser',
            'password': 'password123'
        })
        assert response.status_code == 201
        assert response.get_json()['message'] == 'User created successfully'
    
    def test_register_duplicate_username(self, client):
        client.post('/api/auth/register', json={'username': 'testuser', 'password': 'pass1234'})
        response = client.post('/api/auth/register', json={
            'username': 'testuser',
            'password': 'pass1234'
        })
        assert response.status_code == 400
        assert 'Username already exists' in response.get_json()['error']
    
    def test_first_user_is_admin(self, client):
        response = client.post('/api/auth/register', json={
            'username': 'first',
            'password': 'pass1234'
        })
        assert response.status_code == 201
        with flask_app.app_context():
            user = User.query.filter_by(username='first').first()
            assert user.role == 'admin'
    
    def test_login_success(self, client):
        client.post('/api/auth/register', json={'username': 'user1', 'password': 'pass1234'})
        response = client.post('/api/auth/login', json={
            'username': 'user1',
            'password': 'pass1234'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['username'] == 'user1'

    def test_login_username_is_case_insensitive(self, client):
        client.post('/api/auth/register', json={'username': 'CaseUser', 'password': 'pass1234'})
        response = client.post('/api/auth/login', json={'username': 'caseuser', 'password': 'pass1234'})
        assert response.status_code == 200
        assert response.get_json()['username'] == 'CaseUser'

    def test_login_username_unicode_case_insensitive(self, client):
        client.post('/api/auth/register', json={'username': 'Änne', 'password': 'pass1234'})
        for username in ('Änne', 'änne', 'ÄNNE'):
            response = client.post('/api/auth/login', json={'username': username, 'password': 'pass1234'})
            assert response.status_code == 200
            assert response.get_json()['username'] == 'Änne'

    def test_forgot_and_reset_password_username_is_case_insensitive(self, client, app):
        client.post('/api/auth/register', json={'username': 'CaseUser', 'password': 'pass1234'})
        client.post('/api/auth/forgot-password', json={'username': 'caseuser'})
        with flask_app.app_context():
            from models import PasswordResetToken
            assert PasswordResetToken.query.first() is not None
        token = issue_reset_token(app, 'CaseUser')
        response = client.post('/api/auth/reset-password', json={
            'username': 'CASEUSER', 'token': token, 'new_password': 'newpass123'})
        assert response.status_code == 200
        assert client.post('/api/auth/login', json={
            'username': 'CaseUser', 'password': 'newpass123'}).status_code == 200

    def test_login_password_is_case_sensitive(self, client):
        client.post('/api/auth/register', json={'username': 'casepass', 'password': 'Pass1234'})
        response = client.post('/api/auth/login', json={'username': 'casepass', 'password': 'pass1234'})
        assert response.status_code == 401

    def test_register_rejects_case_variant_duplicate(self, client):
        client.post('/api/auth/register', json={'username': 'CaseUser', 'password': 'pass1234'})
        response = client.post('/api/auth/register', json={'username': 'caseuser', 'password': 'pass1234'})
        assert response.status_code == 400
        assert 'Username already exists' in response.get_json()['error']
    
    def test_login_invalid_credentials(self, client):
        client.post('/api/auth/register', json={'username': 'user2', 'password': 'pass1234'})
        response = client.post('/api/auth/login', json={
            'username': 'user2',
            'password': 'wrongpass'
        })
        assert response.status_code == 401
    
    def test_logout(self, auth_client):
        response = auth_client.post('/api/auth/logout')
        assert response.status_code == 200
        assert response.get_json()['message'] == 'Logged out'

    def test_logout_via_get_is_rejected(self, auth_client):
        response = auth_client.get('/api/auth/logout')
        assert response.status_code == 405
    
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
        client.post('/api/auth/register', json={'username': 'user1', 'password': 'pass1234'})
        client.post('/api/auth/login', json={'username': 'user1', 'password': 'pass1234'})
        client.post('/api/jobs', json={
            'name': 'User1 Job',
            'hourly_rate': 100,
            'hours_per_day': 8,
            'color': '#18181b'
        })
        
        client.post('/api/auth/register', json={'username': 'user2', 'password': 'pass1234'})
        client.post('/api/auth/login', json={'username': 'user2', 'password': 'pass1234'})
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
        client.post('/api/auth/register', json={'username': 'user1', 'password': 'pass1234'})
        client.post('/api/auth/login', json={'username': 'user1', 'password': 'pass1234'})
        client.post('/api/notes', json={'title': 'User1 Private Note', 'content': 'Secret'})
        
        client.post('/api/auth/register', json={'username': 'user2', 'password': 'pass1234'})
        client.post('/api/auth/login', json={'username': 'user2', 'password': 'pass1234'})
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
        
        client.post('/api/auth/register', json={'username': 'other', 'password': 'pass1234'})
        client.post('/api/auth/login', json={'username': 'other', 'password': 'pass1234'})
        response = client.get('/api/jobs')
        jobs = response.get_json()
        assert all(j['name'] != 'Private Job' for j in jobs)


class TestTargetIntegrity:
    def test_target_unique_constraint_exists(self, app):
        from sqlalchemy import inspect
        with app.app_context():
            constraints = inspect(db.engine).get_unique_constraints('target')
            names = [c['name'] for c in constraints]
            indexes = [i['name'] for i in inspect(db.engine).get_indexes('target')]
            assert 'uq_target_user_month' in names or 'uq_target_user_month' in indexes

    def test_duplicate_target_month_is_rejected(self, auth_client):
        auth_client.post('/api/targets', json={'month': '2026-04', 'amount': 100})
        response = auth_client.post('/api/targets', json={'month': '2026-04', 'amount': 200})
        assert response.status_code == 200
        with flask_app.app_context():
            assert Target.query.filter_by(month='2026-04').count() == 1

    def test_target_update_preserves_work_days(self, auth_client):
        auth_client.post('/api/targets', json={'month': '2026-05', 'amount': 100, 'work_days_per_week': 5})
        auth_client.post('/api/targets', json={'month': '2026-05', 'amount': 200})
        with flask_app.app_context():
            target = Target.query.filter_by(month='2026-05').first()
            assert target.amount == 200.0
            assert target.work_days_per_week == 5.0


class TestExpenseStatsValidation:
    @pytest.mark.parametrize('bad', ['2026-13', '2026-00', 'not-a-month', '202604'])
    def test_invalid_month_rejected(self, auth_client, bad):
        response = auth_client.get(f'/api/expenses/stats?month={bad}')
        assert response.status_code == 400, response.get_data(as_text=True)

    def test_empty_month_falls_back_to_current_month(self, auth_client):
        response = auth_client.get('/api/expenses/stats?month=')
        assert response.status_code == 200
        from validators import utcnow
        assert response.get_json()['month'] == utcnow().strftime('%Y-%m')

    def test_valid_month_accepted(self, auth_client):
        response = auth_client.get('/api/expenses/stats?month=2026-04')
        assert response.status_code == 200

    def test_invalid_expense_type_rejected(self, auth_client):
        response = auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 10, 'description': 'x',
            'expense_type': '<script>alert(1)</script>'
        })
        assert response.status_code == 400
        assert response.get_json()['error'] == 'Invalid expense_type'

    @pytest.mark.parametrize('good', ['daily', 'bills', 'work', 'one-time'])
    def test_valid_expense_types_accepted(self, auth_client, good):
        response = auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 10, 'description': 'x', 'expense_type': good
        })
        assert response.status_code == 201
        assert response.get_json()['expense_type'] == good


class TestExpenseBudgets:
    def test_budgets_require_auth(self, client):
        assert client.get('/api/expenses/budgets').status_code == 401
        assert client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'daily', 'limit_amount': 100
        }).status_code == 401
        assert client.delete('/api/expenses/budgets/1').status_code == 401

    def test_create_budget(self, auth_client):
        response = auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'daily', 'limit_amount': 5000
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['month'] == '2026-04'
        assert data['expense_type'] == 'daily'
        assert data['limit_amount'] == 5000.0
        assert 'id' in data

    def test_upsert_budget_does_not_duplicate(self, auth_client, app):
        first = auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'daily', 'limit_amount': 5000
        })
        second = auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'daily', 'limit_amount': 8000
        })
        assert first.get_json()['id'] == second.get_json()['id']
        assert second.get_json()['limit_amount'] == 8000.0
        budgets = auth_client.get('/api/expenses/budgets?month=2026-04').get_json()
        assert len(budgets) == 1

    def test_same_month_different_types_allowed(self, auth_client):
        for expense_type in ['daily', 'bills', 'work', 'one-time']:
            response = auth_client.post('/api/expenses/budgets', json={
                'month': '2026-04', 'expense_type': expense_type, 'limit_amount': 1000
            })
            assert response.status_code == 200
        budgets = auth_client.get('/api/expenses/budgets?month=2026-04').get_json()
        assert len(budgets) == 4

    def test_create_budget_invalid_month(self, auth_client):
        response = auth_client.post('/api/expenses/budgets', json={
            'month': '2026-13', 'expense_type': 'daily', 'limit_amount': 100
        })
        assert response.status_code == 400

    def test_create_budget_invalid_type(self, auth_client):
        response = auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'luxury', 'limit_amount': 100
        })
        assert response.status_code == 400
        assert response.get_json()['error'] == 'Invalid expense_type'

    @pytest.mark.parametrize('bad', [[], {}, 5, None])
    def test_expense_type_non_string_returns_400(self, auth_client, bad):
        budget_res = auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': bad, 'limit_amount': 100
        })
        assert budget_res.status_code == 400
        create_res = auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 10, 'description': 'x', 'expense_type': bad
        })
        assert create_res.status_code == 400
        expense_id = auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 10, 'description': 'x'
        }).get_json()['id']
        update_res = auth_client.put(f'/api/expenses/{expense_id}', json={'expense_type': bad})
        assert update_res.status_code == 400

    @pytest.mark.parametrize('bad', ['abc', -5, None, True])
    def test_create_budget_invalid_limit(self, auth_client, bad):
        response = auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'daily', 'limit_amount': bad
        })
        assert response.status_code == 400

    def test_get_budgets_month_filter(self, auth_client):
        auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'daily', 'limit_amount': 1000
        })
        auth_client.post('/api/expenses/budgets', json={
            'month': '2026-05', 'expense_type': 'daily', 'limit_amount': 2000
        })
        all_budgets = auth_client.get('/api/expenses/budgets').get_json()
        assert len(all_budgets) == 2
        april = auth_client.get('/api/expenses/budgets?month=2026-04').get_json()
        assert len(april) == 1
        assert april[0]['limit_amount'] == 1000.0

    def test_get_budgets_invalid_month_filter(self, auth_client):
        response = auth_client.get('/api/expenses/budgets?month=bad')
        assert response.status_code == 400

    def test_get_budgets_empty_month_returns_all(self, auth_client):
        auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'daily', 'limit_amount': 1000
        })
        response = auth_client.get('/api/expenses/budgets?month=')
        assert response.status_code == 200
        assert len(response.get_json()) == 1

    def test_stats_denormal_limit_no_infinite_percent(self, auth_client):
        auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'daily', 'limit_amount': 1e-320
        })
        auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 10, 'description': 'x', 'expense_type': 'daily'
        })
        response = auth_client.get('/api/expenses/stats?month=2026-04')
        assert response.status_code == 200
        data = response.get_json()
        assert data['budgets']['daily']['percent'] is None
        assert data['budgets']['daily']['status'] == 'over'
        assert 'Infinity' not in response.get_data(as_text=True)

    def test_delete_budget(self, auth_client):
        budget_id = auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'daily', 'limit_amount': 1000
        }).get_json()['id']
        response = auth_client.delete(f'/api/expenses/budgets/{budget_id}')
        assert response.status_code == 200
        assert auth_client.get('/api/expenses/budgets').get_json() == []

    def test_budgets_isolated_per_user(self, auth_client, client):
        budget_id = auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'daily', 'limit_amount': 1000
        }).get_json()['id']
        client.post('/api/auth/register', json={'username': 'intruder', 'password': 'pass1234'})
        client.post('/api/auth/login', json={'username': 'intruder', 'password': 'pass1234'})
        assert client.get('/api/expenses/budgets').get_json() == []
        assert client.delete(f'/api/expenses/budgets/{budget_id}').status_code == 404
        assert client.get('/api/expenses/budgets?month=2026-04').get_json() == []

    def test_stats_budget_statuses(self, auth_client):
        auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'daily', 'limit_amount': 1000
        })
        auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'bills', 'limit_amount': 1000
        })
        auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'work', 'limit_amount': 1000
        })
        auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 500, 'description': 'ok', 'expense_type': 'daily'
        })
        auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 850, 'description': 'warn', 'expense_type': 'bills'
        })
        auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 1200, 'description': 'over', 'expense_type': 'work'
        })
        data = auth_client.get('/api/expenses/stats?month=2026-04').get_json()
        assert data['month'] == '2026-04'
        budgets = data['budgets']
        assert budgets['daily']['status'] == 'ok'
        assert budgets['daily']['limit_amount'] == 1000.0
        assert budgets['daily']['spent'] == 500.0
        assert budgets['daily']['remaining'] == 500.0
        assert budgets['daily']['percent'] == 50.0
        assert budgets['bills']['status'] == 'warning'
        assert budgets['work']['status'] == 'over'
        assert budgets['work']['remaining'] == -200.0
        assert budgets['one-time']['status'] == 'unset'
        assert budgets['one-time']['limit_amount'] is None
        assert budgets['one-time']['spent'] == 0

    def test_stats_zero_limit_budget(self, auth_client):
        auth_client.post('/api/expenses/budgets', json={
            'month': '2026-04', 'expense_type': 'daily', 'limit_amount': 0
        })
        data = auth_client.get('/api/expenses/stats?month=2026-04').get_json()
        assert data['budgets']['daily']['status'] == 'ok'
        assert data['budgets']['daily']['percent'] is None
        auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 10, 'description': 'x', 'expense_type': 'daily'
        })
        data = auth_client.get('/api/expenses/stats?month=2026-04').get_json()
        assert data['budgets']['daily']['status'] == 'over'

    def test_stats_budget_scoped_to_month(self, auth_client):
        auth_client.post('/api/expenses/budgets', json={
            'month': '2026-05', 'expense_type': 'daily', 'limit_amount': 1000
        })
        data = auth_client.get('/api/expenses/stats?month=2026-04').get_json()
        assert data['budgets']['daily']['status'] == 'unset'


class TestJobEditFlow:
    def test_show_job_modal_receives_numeric_id(self, app):
        """The edit button passes job.id; showJobModal must match it against state.jobs."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'static', 'js', 'app.js'), encoding='utf-8') as fh:
            script = fh.read()
        assert 'state.jobs.find(j => j.id === Number(jobId))' in script

    def test_job_rename_updates_existing_income_snapshots(self, auth_client, sample_job):
        auth_client.post('/api/income', json={
            'job_id': sample_job['id'], 'date': '2026-04-09', 'amount': 100
        })
        response = auth_client.put(f'/api/jobs/{sample_job["id"]}', json={'name': 'Fresh Name'})
        assert response.status_code == 200
        records = auth_client.get('/api/income').get_json()
        assert records[0]['job_name'] == 'Fresh Name'

    def test_job_update_via_api(self, auth_client, sample_job):
        response = auth_client.put(f'/api/jobs/{sample_job["id"]}', json={
            'name': 'Renamed Job', 'hourly_rate': 300, 'hours_per_day': 5
        })
        assert response.status_code == 200
        assert response.get_json()['name'] == 'Renamed Job'
        assert response.get_json()['hourly_rate'] == 300.0


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


class TestCrossUserJobIsolation:
    """Regression tests for the cross-tenant Job IDOR (C1/C2)."""

    @pytest.fixture
    def other_user_job(self, app):
        with app.app_context():
            hashed = bcrypt.generate_password_hash('pass1234').decode('utf-8')
            other = User(username='otheruser', password_hash=hashed, role='user')
            db.session.add(other)
            db.session.commit()
            job = Job(name='OtherSecretJob', hourly_rate=999, hours_per_day=8,
                      color='#18181b', user_id=other.id)
            db.session.add(job)
            db.session.commit()
            return job.id

    def test_cannot_create_income_against_other_users_job(self, auth_client, other_user_job):
        response = auth_client.post('/api/income', json={
            'job_id': other_user_job, 'date': '2026-04-09', 'amount': 5
        })
        assert response.status_code == 400
        assert response.get_json()['error'] == 'Job not found'
        assert 'OtherSecretJob' not in response.get_data(as_text=True)

    def test_cannot_repoint_income_at_other_users_job(self, auth_client, sample_job, other_user_job):
        create = auth_client.post('/api/income', json={
            'job_id': sample_job['id'], 'date': '2026-04-09', 'amount': 5
        })
        record_id = create.get_json()['id']
        response = auth_client.put(f'/api/income/{record_id}', json={
            'job_id': other_user_job, 'date': '2026-04-10', 'amount': 7
        })
        assert response.status_code == 400
        assert 'OtherSecretJob' not in response.get_data(as_text=True)

    def test_auto_amount_does_not_leak_other_users_rate(self, auth_client, other_user_job):
        response = auth_client.post('/api/income', json={
            'job_id': other_user_job, 'date': '2026-04-09', 'amount': 0
        })
        assert response.status_code == 400
        assert '7992' not in response.get_data(as_text=True)


class TestIncomeItemGet:
    def test_get_income_item_returns_200(self, auth_client, sample_job):
        create = auth_client.post('/api/income', json={
            'job_id': sample_job['id'], 'date': '2026-04-09', 'amount': 100
        })
        record_id = create.get_json()['id']
        response = auth_client.get(f'/api/income/{record_id}')
        assert response.status_code == 200
        assert response.get_json()['id'] == record_id

    def test_get_income_item_other_user_404(self, auth_client, client):
        job = auth_client.post('/api/jobs', json={
            'name': 'Mine', 'hourly_rate': 10, 'hours_per_day': 1
        }).get_json()
        create = auth_client.post('/api/income', json={
            'job_id': job['id'], 'date': '2026-04-09', 'amount': 100
        })
        record_id = create.get_json()['id']

        client.post('/api/auth/register', json={'username': 'intruder', 'password': 'pass1234'})
        client.post('/api/auth/login', json={'username': 'intruder', 'password': 'pass1234'})
        assert client.get(f'/api/income/{record_id}').status_code == 404


class TestMalformedBodies:
    """Every mutating endpoint must answer 400, never 500 (M1-M3)."""

    ENDPOINTS = [
        ('post', '/api/jobs', {}),
        ('post', '/api/income', {}),
        ('post', '/api/targets', {}),
        ('post', '/api/expenses', {}),
        ('post', '/api/notes', {}),
        ('post', '/api/auth/register', {}),
    ]

    @pytest.mark.parametrize('method,path,payload', ENDPOINTS)
    def test_missing_body_returns_400(self, auth_client, method, path, payload):
        response = getattr(auth_client, method)(path)
        assert response.status_code == 400, response.get_data(as_text=True)
        assert response.get_json()['error'] == 'Invalid request body'

    @pytest.mark.parametrize('method,path,payload', ENDPOINTS)
    def test_json_array_body_returns_400(self, auth_client, method, path, payload):
        response = getattr(auth_client, method)(path, json=[1, 2])
        assert response.status_code == 400, response.get_data(as_text=True)

    def test_missing_required_keys_return_400(self, auth_client):
        assert auth_client.post('/api/jobs', json={'hourly_rate': 1}).status_code == 400
        assert auth_client.post('/api/income', json={'date': '2026-01-01'}).status_code == 400
        assert auth_client.post('/api/targets', json={'amount': 1}).status_code == 400
        assert auth_client.post('/api/expenses', json={'amount': 1}).status_code == 400

    def test_non_json_content_type_returns_400(self, auth_client):
        response = auth_client.post('/api/jobs', data='name=x', content_type='text/plain')
        assert response.status_code == 400
        assert response.get_json()['error'] == 'Invalid request body'


class TestAmountValidation:
    @pytest.mark.parametrize('bad', ['nan', 'inf', '-inf', -500, 'abc', None])
    def test_invalid_expense_amounts_rejected(self, auth_client, bad):
        response = auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': bad, 'description': 'x'
        })
        assert response.status_code == 400, response.get_data(as_text=True)

    @pytest.mark.parametrize('bad', [True, False])
    def test_boolean_amounts_rejected(self, auth_client, sample_job, bad):
        response = auth_client.post('/api/income', json={
            'job_id': sample_job['id'], 'date': '2026-04-09', 'amount': bad
        })
        assert response.status_code == 400

    @pytest.mark.parametrize('bad', ['nan', 'inf', '-inf', -500, 'abc'])
    def test_invalid_income_amounts_rejected(self, auth_client, sample_job, bad):
        response = auth_client.post('/api/income', json={
            'job_id': sample_job['id'], 'date': '2026-04-09', 'amount': bad
        })
        assert response.status_code == 400, response.get_data(as_text=True)

    def test_null_income_amount_rejected(self, auth_client, sample_job):
        response = auth_client.post('/api/income', json={
            'job_id': sample_job['id'], 'date': '2026-04-09', 'amount': None
        })
        assert response.status_code == 400

    def test_empty_amount_uses_job_default(self, auth_client, sample_job):
        """The frontend sends amount:'' when the field is left blank."""
        response = auth_client.post('/api/income', json={
            'job_id': sample_job['id'], 'date': '2026-04-09', 'amount': ''
        })
        assert response.status_code == 201
        assert response.get_json()['amount'] == 1600.0

    def test_omitted_amount_uses_job_default(self, auth_client, sample_job):
        response = auth_client.post('/api/income', json={
            'job_id': sample_job['id'], 'date': '2026-04-09'
        })
        assert response.status_code == 201
        assert response.get_json()['amount'] == 1600.0

    @pytest.mark.parametrize('bad', ['nan', 'inf', -500, 'abc', None])
    def test_invalid_target_amounts_rejected(self, auth_client, bad):
        response = auth_client.post('/api/targets', json={'month': '2026-04', 'amount': bad})
        assert response.status_code == 400, response.get_data(as_text=True)

    def test_expense_put_invalid_amount_rejected(self, auth_client):
        create = auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 10, 'description': 'x'
        })
        expense_id = create.get_json()['id']
        response = auth_client.put(f'/api/expenses/{expense_id}', json={'amount': None})
        assert response.status_code == 400

    def test_infinity_does_not_poison_admin_totals(self, auth_client, sample_job):
        auth_client.post('/api/income', json={
            'job_id': sample_job['id'], 'date': '2026-04-09', 'amount': 'inf'
        })
        with flask_app.app_context():
            from sqlalchemy import func
            total = db.session.query(func.sum(IncomeRecord.amount)).scalar() or 0
            assert total == 0


class TestIncomeAmountConsistency:
    def _create(self, auth_client, sample_job, amount=None):
        payload = {'job_id': sample_job['id'], 'date': '2026-04-09'}
        if amount is not None:
            payload['amount'] = amount
        response = auth_client.post('/api/income', json=payload)
        assert response.status_code == 201, response.get_data(as_text=True)
        return response.get_json()['id']

    def _put(self, auth_client, sample_job, record_id, **extra):
        payload = {'job_id': sample_job['id'], 'date': '2026-04-09'}
        payload.update(extra)
        return auth_client.put(f'/api/income/{record_id}', json=payload)

    def test_put_zero_means_job_default(self, auth_client, sample_job):
        record_id = self._create(auth_client, sample_job, 100)
        response = self._put(auth_client, sample_job, record_id, amount=0)
        assert response.status_code == 200
        assert response.get_json()['amount'] == 1600.0

    def test_put_empty_string_means_job_default(self, auth_client, sample_job):
        record_id = self._create(auth_client, sample_job, 100)
        response = self._put(auth_client, sample_job, record_id, amount='')
        assert response.status_code == 200
        assert response.get_json()['amount'] == 1600.0

    def test_put_omitted_amount_preserves_existing_value(self, auth_client, sample_job):
        record_id = self._create(auth_client, sample_job, 250)
        response = self._put(auth_client, sample_job, record_id)
        assert response.status_code == 200
        assert response.get_json()['amount'] == 250.0

    def test_put_explicit_amount_still_works(self, auth_client, sample_job):
        record_id = self._create(auth_client, sample_job, 250)
        response = self._put(auth_client, sample_job, record_id, amount=999)
        assert response.status_code == 200
        assert response.get_json()['amount'] == 999.0

    def test_put_null_amount_rejected(self, auth_client, sample_job):
        record_id = self._create(auth_client, sample_job, 250)
        response = self._put(auth_client, sample_job, record_id, amount=None)
        assert response.status_code == 400


class TestDateValidation:
    @pytest.mark.parametrize('bad', ['not-a-date', '2026-13-45', '2026-02-31', '20260101', '', 'x' * 50])
    def test_invalid_expense_dates_rejected(self, auth_client, bad):
        response = auth_client.post('/api/expenses', json={
            'date': bad, 'amount': 10, 'description': 'x'
        })
        assert response.status_code == 400, response.get_data(as_text=True)

    @pytest.mark.parametrize('bad', ['not-a-date', '2026-13-45', '20260101', ''])
    def test_invalid_income_dates_rejected(self, auth_client, sample_job, bad):
        response = auth_client.post('/api/income', json={
            'job_id': sample_job['id'], 'date': bad, 'amount': 10
        })
        assert response.status_code == 400, response.get_data(as_text=True)

    @pytest.mark.parametrize('bad', ['not-a-month', '2026-13', '202604', '', '<img src=x>'])
    def test_invalid_target_months_rejected(self, auth_client, bad):
        response = auth_client.post('/api/targets', json={'month': bad, 'amount': 100})
        assert response.status_code == 400, response.get_data(as_text=True)


class TestAdminRoleSafety:
    def test_invalid_role_rejected(self, admin_client):
        with flask_app.app_context():
            hashed = bcrypt.generate_password_hash('pass1234').decode('utf-8')
            user = User(username='targetrole', password_hash=hashed, role='user')
            db.session.add(user)
            db.session.commit()
            user_id = user.id
        response = admin_client.put(f'/api/admin/users/{user_id}', json={'role': 'superadmin'})
        assert response.status_code == 400
        with flask_app.app_context():
            assert db.session.get(User, user_id).role == 'user'

    def test_admin_cannot_demote_self(self, admin_client):
        admin_id = admin_client.get('/api/auth/me').get_json()['id']
        response = admin_client.put(f'/api/admin/users/{admin_id}', json={'role': 'user'})
        assert response.status_code == 400
        with flask_app.app_context():
            assert db.session.get(User, admin_id).role == 'admin'

    def test_admin_cannot_delete_self(self, admin_client):
        admin_id = admin_client.get('/api/auth/me').get_json()['id']
        response = admin_client.delete(f'/api/admin/users/{admin_id}')
        assert response.status_code == 400
        with flask_app.app_context():
            assert db.session.get(User, admin_id) is not None


class TestAdminBootstrap:
    def test_first_ever_user_becomes_admin(self, app):
        response = app.test_client().post('/api/auth/register', json={
            'username': 'firstever', 'password': 'pass1234'
        })
        assert response.status_code == 201
        with flask_app.app_context():
            user = User.query.filter_by(username='firstever').first()
            assert user.role == 'admin'

    def test_registration_after_all_users_deleted_is_not_admin(self, app):
        with flask_app.app_context():
            hashed = bcrypt.generate_password_hash('pass1234').decode('utf-8')
            db.session.add(User(username='originaladmin', password_hash=hashed, role='admin'))
            mark_bootstrap_done()
            db.session.commit()
            for user in User.query.all():
                db.session.delete(user)
            db.session.commit()

        response = app.test_client().post('/api/auth/register', json={
            'username': 'mallory', 'password': 'pass1234'
        })
        assert response.status_code == 201
        with flask_app.app_context():
            user = User.query.filter_by(username='mallory').first()
            assert user.role == 'user'

    def test_registration_on_legacy_db_without_marker_is_not_admin(self, app):
        """Upgraded installs have users but no `setting` row: registration must not be admin."""
        with flask_app.app_context():
            from models import Setting
            hashed = bcrypt.generate_password_hash('pass1234').decode('utf-8')
            db.session.add(User(username='realadmin', password_hash=hashed, role='admin'))
            db.session.commit()
            assert Setting.query.filter_by(key='admin_bootstrap_done').first() is None

        response = app.test_client().post('/api/auth/register', json={
            'username': 'attacker', 'password': 'pass1234'
        })
        assert response.status_code == 201
        with flask_app.app_context():
            user = User.query.filter_by(username='attacker').first()
            assert user.role == 'user'
            admin = User.query.filter_by(username='realadmin').first()
            assert admin.role == 'admin'

    def test_bootstrap_marker_is_created_on_first_registration(self, app):
        with flask_app.app_context():
            from models import Setting
            assert Setting.query.filter_by(key='admin_bootstrap_done').first() is None
        app.test_client().post('/api/auth/register', json={
            'username': 'firstever', 'password': 'pass1234'
        })
        with flask_app.app_context():
            from models import Setting
            assert Setting.query.filter_by(key='admin_bootstrap_done').first() is not None


class TestJobDeletionSafety:
    def test_job_with_income_records_cannot_be_deleted(self, auth_client, sample_job):
        auth_client.post('/api/income', json={
            'job_id': sample_job['id'], 'date': '2026-04-09', 'amount': 100
        })
        response = auth_client.delete(f'/api/jobs/{sample_job["id"]}')
        assert response.status_code == 409
        with flask_app.app_context():
            assert IncomeRecord.query.count() == 1

    def test_empty_job_can_be_deleted(self, auth_client, sample_job):
        response = auth_client.delete(f'/api/jobs/{sample_job["id"]}')
        assert response.status_code == 200
        with flask_app.app_context():
            assert IncomeRecord.query.count() == 0


class TestSecurityHeaders:
    def test_security_headers_present(self, client):
        response = client.get('/')
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.headers['X-Frame-Options'] == 'DENY'
        assert response.headers['Referrer-Policy'] == 'same-origin'

    def test_api_responses_are_not_cached(self, auth_client):
        response = auth_client.get('/api/jobs')
        assert response.headers.get('Cache-Control') == 'no-store'

    def test_session_cookie_is_samesite_lax(self, app):
        assert app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
        assert app.config['SESSION_COOKIE_HTTPONLY'] is True
        assert app.config['REMEMBER_COOKIE'] is False


class TestInputSanitisation:
    def test_job_color_must_be_hex(self, auth_client):
        response = auth_client.post('/api/jobs', json={
            'name': 'Test', 'hourly_rate': 10, 'hours_per_day': 1,
            'color': 'red; background: url(evil)'
        })
        assert response.status_code == 201
        assert response.get_json()['color'] == '#18181b'

    def test_job_name_length_capped(self, auth_client):
        response = auth_client.post('/api/jobs', json={
            'name': 'A' * 300, 'hourly_rate': 10, 'hours_per_day': 1
        })
        assert response.status_code == 400
        assert 'at most 100 characters' in response.get_json()['error']

    def test_expense_description_length_capped(self, auth_client):
        response = auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 10, 'description': 'D' * 400
        })
        assert response.status_code == 400
        assert 'at most 200 characters' in response.get_json()['error']

    def test_expense_tags_must_be_list_or_string(self, auth_client):
        response = auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 10, 'description': 'x', 'tags': {'a': 1}
        })
        assert response.status_code == 201
        assert response.get_json()['tags'] == []

    def test_expense_tags_length_capped(self, auth_client):
        response = auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 10, 'description': 'x', 'tags': ['t' * 800]
        })
        assert response.status_code == 201
        assert len(response.get_json()['tags'][0]) <= 500


class TestXSSEscaping:
    """Regression tests proving API data cannot inject markup into the SPA (S2)."""

    XSS_PAYLOAD = '<img src=x onerror=alert(1)>'
    ATTR_PAYLOAD = '"><script>alert(1)</script>'
    JS_PAYLOAD = "x');alert(document.cookie);//"

    def _template(self, name='index.html'):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        parts = []
        with open(os.path.join(root, 'templates', name), encoding='utf-8') as fh:
            parts.append(fh.read())
        js_map = {'index.html': 'app.js', 'note.html': 'notes.js'}
        if name in js_map:
            js_path = os.path.join(root, 'static', 'js', js_map[name])
            if os.path.exists(js_path):
                with open(js_path, encoding='utf-8') as fh:
                    parts.append(fh.read())
        return '\n'.join(parts)

    @pytest.mark.parametrize('pattern', [
        r'\$\{job\.name\}',
        r'\$\{job\.color\}',
        r'\$\{mainJob\.color\}',
        r'\$\{record\.job_name\}',
        r'\$\{e\.description\}',
        r'\$\{t\.month\}',
        r'\$\{user\.username\}',
        r'\$\{act\.username\}',
        r'\$\{act\.job_name\}',
        r'#\$\{tag\}',
        r'data-color="\$\{job\.color\}"',
    ])
    def test_no_raw_interpolation_of_api_fields(self, pattern):
        template = self._template()
        hits = re.findall(pattern, template)
        assert not hits, f'raw interpolation found: {hits[:3]}'

    def test_escapers_neutralise_html_payloads(self):
        template = self._template()
        assert 'const escHtml' in template
        assert 'const escJs' in template
        for escaper in ('&amp;', '&lt;', '&gt;', '&quot;', '&#39;'):
            assert escaper in template

    def test_escaper_covers_quote_breaks(self):
        template = self._template()
        esc_html = re.search(r'const escHtml = \(s = \'\'\) =>.*?replace\(/\'/g, \'&#39;\'\);', template, re.S)
        assert esc_html is not None, 'escHtml helper not found'
        body = esc_html.group(0)
        assert '&quot;' in body, 'escHtml must escape double quotes'
        assert '&#39;' in body, 'escHtml must escape single quotes'

    def test_note_template_escapes_quotes(self):
        template = self._template('note.html')
        esc_html = re.search(r'function escHtml\(s\) \{.*?\}', template, re.S)
        assert esc_html is not None
        body = esc_html.group(0)
        assert '&quot;' in body
        assert '&#39;' in body

    def test_xss_payloads_are_stored_but_escaped_on_render(self, auth_client):
        job = auth_client.post('/api/jobs', json={
            'name': self.XSS_PAYLOAD, 'hourly_rate': 10, 'hours_per_day': 1
        }).get_json()
        assert job['name'] == self.XSS_PAYLOAD

        expense = auth_client.post('/api/expenses', json={
            'date': '2026-04-09', 'amount': 10,
            'description': self.XSS_PAYLOAD, 'tags': [self.JS_PAYLOAD]
        }).get_json()
        assert expense['description'] == self.XSS_PAYLOAD

        template = self._template()
        assert f"${{escHtml(job.name)}}" in template or "escHtml(job.name)" in template

    def test_inline_handlers_do_not_use_raw_json_stringify(self):
        template = self._template()
        assert 'JSON.stringify(job).replace' not in template

    def test_inline_handler_arguments_use_handler_escaper(self):
        template = self._template()
        # Values interpolated into onclick="fn(...)" must use the attribute-aware escaper.
        handler_calls = re.findall(r'onclick="[^"]*\$\{esc(Js|HandlerArg)\(([^)]*)\)\}', template)
        assert handler_calls, 'no inline handler interpolation found to check'
        for escaper, _ in handler_calls:
            assert escaper == 'HandlerArg', (
                'inline handler argument uses escJs, which emits raw double quotes and '
                'breaks out of the HTML attribute'
            )
    def test_handler_escaper_encodes_html_then_js_once(self):
        template = self._template()
        body = re.search(r'const escHandlerArg = .*?;', template, re.S)
        assert body is not None, 'escHandlerArg helper not found'
        source = body.group(0)
        # escAttr (HTML entity encoding) must be applied to the escJs (JS) output,
        # exactly once. Applying it twice double-encodes and breaks the value.
        assert 'escAttr(escJs(' in source
        assert source.count('escAttr(') == 1

    def test_handler_escaper_round_trips_payloads(self):
        template = self._template()
        assert 'const escHandlerArg' in template
        # The helper must entity-encode the double quote produced by JSON encoding.
        assert "escAttr" in template
        assert ".replace(/\"/g, '&quot;')" in template



class TestUsernameMigration:
    """The backfill must use the same NFKC+casefold rule the app uses at runtime."""

    def _insert_legacy_user(self, username, normalized, role='user', user_id=None):
        from sqlalchemy import text
        params = {
            'u': username,
            'n': normalized,
            'h': bcrypt.generate_password_hash('pass1234').decode('utf-8'),
            'r': role,
        }
        if user_id is None:
            db.session.execute(text(
                "INSERT INTO user (username, username_normalized, password_hash, role) "
                "VALUES (:u, :n, :h, :r)"
            ), params)
        else:
            params['i'] = user_id
            db.session.execute(text(
                "INSERT INTO user (id, username, username_normalized, password_hash, role) "
                "VALUES (:i, :u, :n, :h, :r)"
            ), params)
        db.session.commit()

    def _drop_unique_index(self):
        """Legacy installs gain the column via ALTER TABLE, so it has no unique index yet."""
        from sqlalchemy import text
        db.session.execute(text("DROP INDEX IF EXISTS ix_user_username_normalized"))
        db.session.commit()

    def test_backfill_repairs_non_ascii_usernames(self, app):
        from sqlalchemy import text
        from app import _backfill_normalized_usernames
        with app.app_context():
            # Simulate what SQL lower() leaves behind on SQLite / PostgreSQL.
            self._insert_legacy_user('ÄÖÜ', 'ÄÖÜ')
            self._insert_legacy_user('ﬁnance', 'ﬁnance')
            _backfill_normalized_usernames()
            rows = dict(db.session.execute(
                text("SELECT username, username_normalized FROM user")
            ).fetchall())
            assert rows['ÄÖÜ'] == 'äöü'
            assert rows['ﬁnance'] == 'finance'

    def test_legacy_non_ascii_account_can_log_in_after_backfill(self, app):
        from app import _backfill_normalized_usernames
        with app.app_context():
            self._insert_legacy_user('ÄÖÜ', 'ÄÖÜ', role='admin')
            _backfill_normalized_usernames()
        client = app.test_client()
        response = client.post('/api/auth/login', json={'username': 'äöü', 'password': 'pass1234'})
        assert response.status_code == 200, response.get_data(as_text=True)

    def test_duplicate_accounts_are_renamed_and_keep_their_data(self, app):
        from sqlalchemy import text
        from app import _drop_duplicate_normalized_users
        with app.app_context():
            self._drop_unique_index()
            self._insert_legacy_user('Alice', 'alice', role='admin', user_id=1)
            self._insert_legacy_user('alice', 'alice', role='user', user_id=2)
            job = Job(user_id=2, name='Legacy Job', hourly_rate=10, hours_per_day=1)
            db.session.add(job)
            db.session.commit()
            job_id = job.id

            _drop_duplicate_normalized_users()

            users = db.session.execute(text(
                "SELECT id, username, role FROM user ORDER BY id"
            )).fetchall()
            assert len(users) == 2, 'duplicate account must be renamed, not deleted'
            assert users[0].username == 'Alice' and users[0].role == 'admin'
            assert users[1].username.startswith('alice-dup')
            owner = db.session.execute(
                text("SELECT user_id FROM job WHERE id = :i"), {'i': job_id}
            ).fetchone()
            assert owner.user_id == 2

    def test_duplicate_rename_stays_within_username_length(self, app):
        from sqlalchemy import text
        from app import _drop_duplicate_normalized_users, MAX_USERNAME_LEN
        with app.app_context():
            self._drop_unique_index()
            upper = 'A' * 79 + 'B'
            lower = 'a' * 79 + 'b'
            assert len(upper) == MAX_USERNAME_LEN
            self._insert_legacy_user(upper, upper, user_id=1)
            self._insert_legacy_user(lower, lower, user_id=2)
            _drop_duplicate_normalized_users()
            names = [row.username for row in db.session.execute(text("SELECT username FROM user")).fetchall()]
            assert len(set(names)) == 2
            assert all(len(name) <= MAX_USERNAME_LEN for name in names)

    def test_duplicate_rename_keeps_admin_account(self, app):
        from sqlalchemy import text
        from app import _drop_duplicate_normalized_users
        with app.app_context():
            self._drop_unique_index()
            # The admin is the higher id: it must survive with its original name.
            self._insert_legacy_user('bob', 'bob', role='user', user_id=1)
            self._insert_legacy_user('BOB', 'bob', role='admin', user_id=2)
            _drop_duplicate_normalized_users()
            admin = db.session.execute(
                text("SELECT username, role FROM user WHERE id = 2")
            ).fetchone()
            assert admin.role == 'admin'
            assert admin.username == 'BOB'
            assert User.query.filter(User.role == 'admin').count() == 1


class TestBootstrapSeed:
    def test_seed_flag_is_not_created_on_empty_database(self, app):
        from app import _seed_bootstrap_flag
        from models import Setting
        with app.app_context():
            assert User.query.count() == 0
            _seed_bootstrap_flag()
            assert Setting.query.filter_by(key='admin_bootstrap_done').first() is None

    def test_first_registration_on_seeded_empty_database_is_admin(self, app):
        from app import _seed_bootstrap_flag
        with app.app_context():
            _seed_bootstrap_flag()
        response = app.test_client().post('/api/auth/register', json={
            'username': 'owner', 'password': 'pass1234'
        })
        assert response.status_code == 201
        with app.app_context():
            assert User.query.filter_by(username='owner').first().role == 'admin'

    def test_seed_flag_is_created_when_users_already_exist(self, app):
        from app import _seed_bootstrap_flag
        from models import Setting
        with app.app_context():
            hashed = bcrypt.generate_password_hash('pass1234').decode('utf-8')
            db.session.add(User(username='existing', password_hash=hashed, role='user'))
            db.session.commit()
            _seed_bootstrap_flag()
            assert Setting.query.filter_by(key='admin_bootstrap_done').first() is not None


class TestUsernameNormalization:
    def test_expanding_codepoints_do_not_overflow_the_column(self, app):
        name = 'ﬁ' * 80
        response = app.test_client().post('/api/auth/register', json={
            'username': name, 'password': 'pass1234'
        })
        assert response.status_code == 201, response.get_data(as_text=True)
        client = app.test_client()
        login = client.post('/api/auth/login', json={'username': name, 'password': 'pass1234'})
        assert login.status_code == 200, login.get_data(as_text=True)
        with app.app_context():
            user = User.query.filter_by(username=name).first()
            assert user is not None
            assert len(user.username_normalized) <= 80

    def test_backfill_repairs_collisions_while_unique_index_exists(self, app):
        from app import _backfill_normalized_usernames

        def insert(username, normalized, user_id):
            from sqlalchemy import text
            db.session.execute(text(
                "INSERT INTO user (id, username, username_normalized, password_hash, role) "
                "VALUES (:i, :u, :n, :h, 'user')"
            ), {
                'i': user_id, 'u': username, 'n': normalized,
                'h': bcrypt.generate_password_hash('pass1234').decode('utf-8'),
            })
            db.session.commit()

        with app.app_context():
            # SQL lower() left these untouched on SQLite; casefold collapses them.
            insert('Å', 'Å', 1)
            insert('å', 'å', 2)
            _backfill_normalized_usernames()
            users = User.query.order_by(User.id).all()
            assert len(users) == 2, 'no account may be deleted'
            assert len({u.username_normalized for u in users}) == 2
            assert users[1].username.startswith('å-dup')


class TestCSRFProtection:
    def test_csrf_token_endpoint_returns_token(self, client):
        response = client.get('/api/auth/csrf-token')
        assert response.status_code == 200
        token = response.get_json().get('csrf_token')
        assert isinstance(token, str) and len(token) >= 32

    def test_templates_include_csrf_meta_tag(self, auth_client):
        index_res = auth_client.get('/')
        assert index_res.status_code == 200
        assert b'<meta name="csrf-token"' in index_res.data
        notes_res = auth_client.get('/notes')
        assert notes_res.status_code == 200
        assert b'<meta name="csrf-token"' in notes_res.data

    def test_mutating_api_rejected_without_csrf_when_enabled(self, app, auth_client):
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            res = auth_client.post('/api/jobs', json={'name': 'NoCSRF', 'hourly_rate': 10, 'hours_per_day': 8})
            assert res.status_code == 403
            assert 'CSRF' in res.get_json()['error']
        finally:
            app.config['WTF_CSRF_ENABLED'] = False

    def test_mutating_api_rejected_with_wrong_csrf_token(self, app, auth_client):
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            auth_client.get('/api/auth/csrf-token')
            res = auth_client.post(
                '/api/jobs',
                json={'name': 'WrongCSRF', 'hourly_rate': 10, 'hours_per_day': 8},
                headers={'X-CSRF-Token': 'wrong-token'},
            )
            assert res.status_code == 403
        finally:
            app.config['WTF_CSRF_ENABLED'] = False

    def test_csrf_token_rotates_on_logout(self, auth_client):
        token_before = auth_client.get('/api/auth/csrf-token').get_json()['csrf_token']
        assert auth_client.post('/api/auth/logout').status_code == 200
        token_after = auth_client.get('/api/auth/csrf-token').get_json()['csrf_token']
        assert token_after != token_before

    def test_mutating_api_succeeds_with_valid_csrf_header(self, app, auth_client):
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            token = auth_client.get('/api/auth/csrf-token').get_json()['csrf_token']
            res = auth_client.post(
                '/api/jobs',
                json={'name': 'WithCSRF', 'hourly_rate': 15, 'hours_per_day': 8},
                headers={'X-CSRF-Token': token},
            )
            assert res.status_code == 201
            assert res.get_json()['name'] == 'WithCSRF'
        finally:
            app.config['WTF_CSRF_ENABLED'] = False


class TestRateLimiting:
    def test_login_rate_limit_enforced_when_enabled(self, app, client):
        from app import rate_limiter

        rate_limiter.reset()
        app.config['RATELIMIT_ENABLED'] = True
        try:
            for _ in range(10):
                res = client.post('/api/auth/login', json={'username': 'nobody', 'password': 'wrong'})
                assert res.status_code == 401
                assert 'X-RateLimit-Limit' in res.headers
                assert 'X-RateLimit-Remaining' in res.headers

            blocked = client.post('/api/auth/login', json={'username': 'nobody', 'password': 'wrong'})
            assert blocked.status_code == 429
            assert 'Retry-After' in blocked.headers
            assert blocked.headers['X-RateLimit-Remaining'] == '0'
            assert 'Too many requests' in blocked.get_json()['error']
        finally:
            app.config.pop('RATELIMIT_ENABLED', None)
            rate_limiter.reset()

    def test_rate_limit_isolated_per_ip(self, app, client):
        from app import rate_limiter

        rate_limiter.reset()
        app.config['RATELIMIT_ENABLED'] = True
        try:
            for _ in range(5):
                client.post(
                    '/api/auth/register',
                    json={'username': '', 'password': ''},
                    environ_base={'REMOTE_ADDR': '10.0.0.1'},
                )
            blocked = client.post(
                '/api/auth/register',
                json={'username': '', 'password': ''},
                environ_base={'REMOTE_ADDR': '10.0.0.1'},
            )
            assert blocked.status_code == 429

            other_ip = client.post(
                '/api/auth/register',
                json={'username': '', 'password': ''},
                environ_base={'REMOTE_ADDR': '10.0.0.2'},
            )
            assert other_ip.status_code == 400
        finally:
            app.config.pop('RATELIMIT_ENABLED', None)
            rate_limiter.reset()


class TestUserProfileAndPasswordChange:
    def test_get_profile_requires_auth(self, client):
        assert client.get('/api/auth/profile').status_code == 401

    def test_get_profile_returns_user_and_stats(self, auth_client, sample_job):
        auth_client.post('/api/income', json={'job_id': sample_job['id'], 'date': '2026-04-09', 'amount': 500})
        auth_client.post('/api/expenses', json={'date': '2026-04-09', 'amount': 50, 'description': 'Coffee'})
        auth_client.post('/api/notes', json={'title': 'Hello', 'content': 'World'})

        res = auth_client.get('/api/auth/profile')
        assert res.status_code == 200
        body = res.get_json()
        assert body['username'] == 'testuser'
        assert body['role'] == 'user'
        assert body['stats'] == {
            'jobs_count': 1,
            'income_records_count': 1,
            'expenses_count': 1,
            'notes_count': 1,
        }

    def test_update_profile_username(self, auth_client):
        res = auth_client.put('/api/auth/profile', json={'username': 'renamed_user'})
        assert res.status_code == 200
        assert res.get_json()['username'] == 'renamed_user'

        me = auth_client.get('/api/auth/me').get_json()
        assert me['username'] == 'renamed_user'

    def test_update_profile_rejects_duplicate_case_insensitive_username(self, app, auth_client):
        with app.app_context():
            hashed = bcrypt.generate_password_hash('secret12').decode('utf-8')
            db.session.add(User(username='TakenUser', password_hash=hashed, role='user'))
            db.session.commit()

        res = auth_client.put('/api/auth/profile', json={'username': 'takenuser'})
        assert res.status_code == 400
        assert 'already exists' in res.get_json()['error']

    def test_update_profile_rejects_empty_and_overlong_username(self, auth_client):
        assert auth_client.put('/api/auth/profile', json={'username': '   '}).status_code == 400
        assert auth_client.put('/api/auth/profile', json={'username': 'a' * 81}).status_code == 400
        assert auth_client.put('/api/auth/profile', json={'username': 123}).status_code == 400

    def test_change_password_success_and_login_with_new_password(self, app, auth_client):
        res = auth_client.post('/api/auth/change-password', json={
            'current_password': 'testpass',
            'new_password': 'newstrongpass'
        })
        assert res.status_code == 200
        assert 'Password updated' in res.get_json()['message']

        auth_client.post('/api/auth/logout')
        old_login = auth_client.post('/api/auth/login', json={'username': 'testuser', 'password': 'testpass'})
        assert old_login.status_code == 401
        new_login = auth_client.post('/api/auth/login', json={'username': 'testuser', 'password': 'newstrongpass'})
        assert new_login.status_code == 200

    def test_change_password_invalidates_unused_reset_tokens(self, app, auth_client):
        token = issue_reset_token(app, username='testuser')
        auth_client.post('/api/auth/login', json={'username': 'testuser', 'password': 'testpass'})
        res = auth_client.post('/api/auth/change-password', json={
            'current_password': 'testpass',
            'new_password': 'newstrongpass'
        })
        assert res.status_code == 200

        reset_res = auth_client.post('/api/auth/reset-password', json={
            'username': 'testuser',
            'token': token,
            'new_password': 'anotherpass'
        })
        assert reset_res.status_code == 400

    def test_change_password_rejects_wrong_current_or_invalid_new(self, auth_client):
        wrong = auth_client.post('/api/auth/change-password', json={
            'current_password': 'wrongpass',
            'new_password': 'newstrongpass'
        })
        assert wrong.status_code == 400
        assert 'incorrect' in wrong.get_json()['error'].lower()

        short = auth_client.post('/api/auth/change-password', json={
            'current_password': 'testpass',
            'new_password': '123'
        })
        assert short.status_code == 400

        too_long = auth_client.post('/api/auth/change-password', json={
            'current_password': 'testpass',
            'new_password': 'x' * 73
        })
        assert too_long.status_code == 400


class TestStaticAssets:
    @pytest.mark.parametrize('path', [
        '/static/css/app.css',
        '/static/js/app.js',
        '/static/js/csrf.js',
        '/static/css/notes.css',
        '/static/js/notes.js',
    ])
    def test_static_assets_served(self, client, path):
        res = client.get(path)
        assert res.status_code == 200
        assert len(res.data) > 0
