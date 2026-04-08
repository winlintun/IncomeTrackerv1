# AGENTS.md - Income Tracker (Flask)

## Quick Start

```bash
pip install -r requirements.txt
python app.py
# App runs at http://localhost:3000
```

## Tech Stack

Python 3.12.1, Flask 3.0, Flask-SQLAlchemy, Flask-Login, Flask-Bcrypt, PostgreSQL

## Commands

| Command | Use |
|---------|-----|
| `python app.py` | Dev server (port 3000) |
| `npm start` | Production (gunicorn) |
| `npm run lint` | Syntax check (`python -m py_compile`) |
| `python -m pytest tests/` | Run TDD tests |

## Project Structure

```
app.py              # Flask app, routes, API endpoints
models.py           # DB models: User, Job, IncomeRecord, Target, Note, Expense
templates/          # index.html (dashboard), note.html (notes page)
```

## Important Behaviors

- **Database URL**: Auto-converts `postgres://` to `postgresql://` (app.py:29-30)
- **DB Init**: Retries 5 times with 3s delay on startup; creates `work_days_per_week` column if missing (app.py:41-59)
- **Admin**: First user becomes admin; only one admin allowed
- **Dates**: Stored as strings `YYYY-MM-DD`; amounts as floats
- **Timestamps**: Use `datetime.utcnow` (not timezone-aware)

## Auth

- `flask_login` for sessions; `@login_required` decorator
- `flask_bcrypt` for password hashing
- Admin routes check `current_user.role == 'admin'`
- Always filter queries by `user_id=current_user.id`

## API Patterns

- `GET /api/resource` - list (filter by user)
- `POST /api/resource` - create
- `PUT /api/resource/<id>` - update (verify ownership)
- `DELETE /api/resource/<id>` - delete
- JSON responses; 201 for create, 400 for bad input, 401/403 for auth errors

## Code Style

- No comments unless requested
- Max line length: 120
- 4-space indentation
- f-strings for string interpolation
- Numeric conversions in try-except

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Flask secret key |
| `DATABASE_URL` | PostgreSQL or SQLite (`sqlite:///path`) |


##  Rule
- Prefer existing abstractions over adding new helpers
- Update tests for behavior changes
- Keep API responses consistent across endpoints


## Strict Code Review Protocol
You are strictly prohibited from telling the human user that a task is completed or considering a job done until you have successfully passed a sub-agent code review. 

Whenever you finish writing, modifying, or completing any code implementation:
1. You MUST immediately spawn the review sub-agent by executing:
   `.opencode\agent\code-reviewer.md"Review the changes I just made. List all issues clearly, or respond with exactly: READY_TO_COMMIT"`
2. Wait for the sub-agent to finish its analysis and return its output.
3. If the sub-agent points out bugs, edge cases, or issues, go back and fix the code.
4. Once fixed, repeat step 1 and call the sub-agent again.
5. You may only stop this cycle and report back to the human when the sub-agent responds with exactly: `READY_TO_COMMIT`.