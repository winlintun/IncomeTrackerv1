# AGENTS.md - Income Tracker (Flask)

## Project Overview

A Flask-based income and expense tracking web application with user authentication, role-based access control, and PostgreSQL database.

**Tech Stack**: Python 3.12, Flask 3.0, Flask-SQLAlchemy, Flask-Login, Flask-Bcrypt, PostgreSQL

---

## Build / Run Commands

### Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py
# App runs at http://localhost:3000
```

### Production
```bash
# Using gunicorn (via package.json)
npm start
# Or directly: gunicorn app:app --bind 0.0.0.0:$PORT
```

### Linting
```bash
# Python syntax check (from package.json)
npm run lint
# Or: python -m py_compile app.py models.py

# For more comprehensive linting (if ruff is installed)
ruff check app.py models.py
```

### Testing
**Note**: This project currently has no tests. If tests are added:

```bash
# Run all tests with pytest
pytest

# Run a single test file
pytest tests/test_auth.py

# Run a single test function
pytest tests/test_auth.py::test_login_success
```

---

## Code Style Guidelines

### General Principles

- **No added comments** unless explicitly requested
- Use existing codebase patterns and conventions
- Follow PEP 8 with 4-space indentation
- Keep functions focused and single-purpose (under 50 lines when possible)

### Imports

**Standard order** (as seen in `app.py`):
1. Built-in Python modules (`os`, `datetime`, `time`)
2. Third-party Flask and SQLAlchemy imports
3. Project local imports (`from models import ...`)

```python
# Example import order
import os
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from models import db, User, Job, IncomeRecord, Target, Note, Expense
from datetime import datetime, timedelta
from sqlalchemy import text
```

### Naming Conventions

- **Variables**: `snake_case` (e.g., `user_id`, `hourly_rate`)
- **Functions**: `snake_case` (e.g., `manage_jobs`, `load_user`)
- **Classes**: `PascalCase` (e.g., `User`, `Job`, `IncomeRecord`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `SECRET_KEY`)
- **Database columns**: `snake_case` (e.g., `user_id`, `password_hash`)
- **API endpoints**: Use descriptive, RESTful paths (e.g., `/api/jobs`, `/api/auth/login`)

### Types

- Use Python type hints where beneficial for clarity
- Use `float` for monetary values and rates
- Use `int` for IDs and counts
- Use `str` for dates (ISO format: `YYYY-MM-DD`), text fields
- Use `bool` for flags (`pinned`, `is_authenticated`)

### Formatting

- Maximum line length: 120 characters
- Use f-strings for string interpolation
- Use list/dict comprehensions where appropriate
- Use `.all()` for query results, `.first_or_404()` for single items
- JSON responses: use dictionaries with consistent key naming

```python
# Good JSON response pattern
return jsonify({
    'id': new_job.id,
    'name': new_job.name,
    'hourly_rate': new_job.hourly_rate,
    'hours_per_day': new_job.hours_per_day,
    'color': new_job.color
}), 201
```

### Database Models (models.py)

- Use `db.Model` base class
- Define columns with explicit types and constraints
- Use `nullable=False` for required fields
- Use `default=` for optional defaults
- Use `db.ForeignKey('table.column')` for relationships
- Use `cascade="all, delete-orphan"` for dependent relationships

```python
class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    hourly_rate = db.Column(db.Float, nullable=False)
    hours_per_day = db.Column(db.Float, nullable=False)
    color = db.Column(db.String(20), default='#18181b')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
```

### Error Handling

- Return proper HTTP status codes:
  - `200` for successful GET/PUT
  - `201` for successful POST
  - `400` for bad request / invalid input
  - `401` for unauthorized
  - `403` for forbidden (role-based)
  - `404` for not found
- Return error details in JSON:

```python
return jsonify({'error': 'Invalid credentials'}), 401
```

- Wrap numeric conversions in try-except:

```python
try:
    hourly_rate = float(data.get('hourly_rate', 0) or 0)
except ValueError:
    return jsonify({'error': 'Invalid numeric values'}), 400
```

### Authentication

- Use `flask_login` for session management
- Use `@login_required` decorator for protected routes
- Use `flask_bcrypt` for password hashing
- Always check `user_id` ownership for data access
- Admin routes must verify `current_user.role == 'admin'`

### Route Patterns

- Use consistent RESTful patterns:
  - `GET /api/resource` - list all
  - `POST /api/resource` - create
  - `GET /api/resource/<id>` - get one
  - `PUT /api/resource/<id>` - update
  - `DELETE /api/resource/<id>` - delete
- Use HTTP method checks for combined endpoints:

```python
@app.route('/api/jobs', methods=['GET', 'POST'])
@login_required
def manage_jobs():
    if request.method == 'POST':
        # create logic
    jobs = Job.query.filter_by(user_id=current_user.id).all()
    return jsonify([...])
```

### Frontend Templates

- Templates use Tailwind CSS via CDN
- Keep JS logic separate in `<script>` tags
- Use fetch API for all backend communication
- Handle errors gracefully with user feedback

---

## Project Structure

```
income-tracker-(flask)/
├── app.py              # Main Flask application, routes, API endpoints
├── models.py            # SQLAlchemy database models
├── requirements.txt     # Python dependencies
├── package.json         # NPM scripts (dev, start, build, lint)
├── pyproject.toml       # Python project config
├── Procfile             # Gunicorn start command (production)
├── runtime.txt          # Python runtime version
├── templates/
│   ├── index.html      # Main dashboard UI
│   └── note.html       # Notes page UI
├── .env                 # Environment variables (secret)
├── .env.example         # Environment template
├── backups/             # Database backups
└── instance/           # SQLite local database (dev only)
```

---

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SECRET_KEY` | Flask secret key for sessions | Yes |
| `DATABASE_URL` | PostgreSQL connection string | Yes |

---

## Common Development Tasks

### Adding a new model
1. Add model class to `models.py`
2. Import and use in `app.py`
3. Add API routes following existing patterns

### Adding a new API endpoint
1. Define route with `@app.route()` and `@login_required`
2. Handle methods with `if request.method == 'POST':`
3. Return JSON with appropriate status codes
4. Test with curl or frontend fetch

### Database migrations
This project uses `db.create_all()` in `app.py`. For schema changes:
1. Update model in `models.py`
2. Restart app (development)
3. For existing databases, add columns manually or use Alembic

---

## Tips for Agents

- The app uses SQLite locally (via `DATABASE_URL` env var) or PostgreSQL in production
- First registered user automatically becomes admin
- Only one admin is allowed at a time
- Dates are stored as strings in `YYYY-MM-DD` format
- Amounts are stored as floats
- Use `db.session.commit()` after modifications
- Use `datetime.utcnow` for timestamps (not timezone-aware)
