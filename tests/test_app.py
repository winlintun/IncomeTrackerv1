import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DB = 'sqlite://'
os.environ['DATABASE_URL'] = TEST_DB

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
            token = reset.token

        response = client.post('/api/auth/reset-password', json={
            'username': 'alice', 'token': token, 'new_password': 'newpass123'
        })
        assert response.status_code == 200

        login = client.post('/api/auth/login', json={'username': 'alice', 'password': 'newpass123'})
        assert login.status_code == 200
        assert client.post('/api/auth/login', json={'username': 'alice', 'password': 'oldpass'}).status_code == 401

    def test_reset_password_invalid_token(self, client):
        client.post('/api/auth/register', json={'username': 'alice', 'password': 'pass123'})
        response = client.post('/api/auth/reset-password', json={
            'username': 'alice', 'token': 'bogus', 'new_password': 'newpass123'
        })
        assert response.status_code == 400

    def test_reset_password_token_reuse_rejected(self, client):
        client.post('/api/auth/register', json={'username': 'alice', 'password': 'pass123'})
        client.post('/api/auth/forgot-password', json={'username': 'alice'})
        with flask_app.app_context():
            from models import PasswordResetToken
            token = PasswordResetToken.query.first().token
        client.post('/api/auth/reset-password', json={'username': 'alice', 'token': token, 'new_password': 'newpass1'})
        response = client.post('/api/auth/reset-password', json={'username': 'alice', 'token': token, 'new_password': 'newpass2'})
        assert response.status_code == 400

    def test_reset_password_short_password_rejected(self, client):
        client.post('/api/auth/register', json={'username': 'alice', 'password': 'pass123'})
        client.post('/api/auth/forgot-password', json={'username': 'alice'})
        with flask_app.app_context():
            from models import PasswordResetToken
            token = PasswordResetToken.query.first().token
        response = client.post('/api/auth/reset-password', json={'username': 'alice', 'token': token, 'new_password': 'abc'})
        assert response.status_code == 400

    def test_reset_password_username_mismatch_rejected(self, client):
        client.post('/api/auth/register', json={'username': 'alice', 'password': 'pass123'})
        client.post('/api/auth/forgot-password', json={'username': 'alice'})
        with flask_app.app_context():
            from models import PasswordResetToken
            token = PasswordResetToken.query.first().token
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

    def test_forgot_password_expires(self, client):
        from datetime import datetime
        client.post('/api/auth/register', json={'username': 'alice', 'password': 'pass123'})
        client.post('/api/auth/forgot-password', json={'username': 'alice'})
        with flask_app.app_context():
            from models import PasswordResetToken
            reset = PasswordResetToken.query.first()
            reset.expires_at = datetime(2020, 1, 1)
            db.session.commit()
            token = reset.token
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

    def test_forgot_and_reset_password_username_is_case_insensitive(self, client):
        client.post('/api/auth/register', json={'username': 'CaseUser', 'password': 'pass1234'})
        client.post('/api/auth/forgot-password', json={'username': 'caseuser'})
        with flask_app.app_context():
            from models import PasswordResetToken
            token = PasswordResetToken.query.first()
            assert token is not None
            token = token.token
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
