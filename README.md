# Income Tracker

A full-stack web application built with Flask and PostgreSQL to help users track their income and expenses. It features user authentication, role-based access control (with a single-admin enforcement), and a responsive UI.

## Features

*   **User Authentication**: Secure registration and login using `Flask-Login` and `Flask-Bcrypt`.
*   **Password Reset**: Forgot-password flow with time-limited, single-use reset codes (30 minutes; printed to server logs or retrievable by the admin — no email dependency).
*   **Dashboard**: View total income, total expenses, and net balance.
*   **Transaction Management**: Add, edit, and delete income and expense records.
*   **Notes**: A separate notes page for quick ideas and reminders.
*   **Job Management**: Track jobs with hourly rates and hours per day; income records can be auto-calculated from them.
*   **Admin Panel**: A dedicated dashboard for the admin to view all users and manage their roles.
*   **Single Admin Rule**: The system strictly enforces that only one user can hold the `admin` role at any given time.
*   **PostgreSQL Database**: Robust data storage using PostgreSQL and `Flask-SQLAlchemy` (SQLite fallback in development).

## Tech Stack

*   **Backend**: Python, Flask, Flask-SQLAlchemy, Flask-Login, Flask-Bcrypt
*   **Database**: PostgreSQL
*   **Frontend**: HTML, JavaScript, Tailwind CSS (via CDN)
*   **Server**: Gunicorn (for production)

## Local Development Setup

1.  **Clone the repository** (if you haven't already):
    ```bash
    git clone <your-repository-url>
    cd IncomeTrackerv1
    ```

2.  **Create a virtual environment**:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use: venv\Scripts\activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Environment Variables**:
    Create a `.env` file in the root directory (copy `.env.example` as a starting point) and add your configuration:
    ```env
    SECRET_KEY=your_super_secret_key_here
    # Local PostgreSQL example
    DATABASE_URL=postgresql://user:password@localhost:5432/yourdb
    # Or SQLite in development
    # DATABASE_URL=sqlite:///income_tracker.sqlite
    # FLASK_ENV=development
    ```
    Required settings:
    *   `SECRET_KEY` — **required in production**. The app refuses to start without it unless `FLASK_ENV` or `APP_ENV` is set to `development` (then it falls back to an insecure dev key).
    *   `DATABASE_URL` — **required in production**. PostgreSQL connection string (`postgres://` URLs are auto-converted to `postgresql://`). In development the app falls back to local SQLite.
    *   `FLASK_ENV=development` or `APP_ENV=development` — optional; enables the local development fallbacks above.
    *   Never commit real credentials: `.env*`, backups, and the SQLite files listed in `.gitignore` are already ignored.

5.  **Run the application**:
    ```bash
    python app.py
    ```
    The app will be available at `http://localhost:3000`.

## Running with Docker

Works the same on Linux, macOS, and Windows. The app connects to **your own PostgreSQL** by default; a bundled PostgreSQL is available as an opt-in.

1.  **Prerequisite**: Docker Desktop (macOS / Windows) or Docker Engine with the Compose plugin (Linux).

2.  **Configure environment**: Copy `.env.example` to `.env`, set a strong `SECRET_KEY`, and point `DATABASE_URL` at your PostgreSQL server — for example a server-side PostgreSQL reached from containers via the Docker bridge gateway (`172.17.0.1` is the native Linux gateway; Docker Desktop on macOS / Windows uses `host.docker.internal` instead):
    ```env
    SECRET_KEY=<generated strong key>
    DATABASE_URL=postgresql://dbuser:<password>@172.17.0.1:5432/yourdb
    ```
    Generate a key with `python -c "import secrets; print(secrets.token_hex(32))"`.
    Real credentials live **only** in `.env`: it is gitignored, excluded from the Docker image, and should be `chmod 600 .env`. Passwords never reach git or image layers. On the wire the password exchange is protected when the role uses a SCRAM-hashed password and `pg_hba.conf` selects `scram-sha-256` (the PostgreSQL 14+ default); SCRAM protects the password, not the data in transit — append `?sslmode=require` to `DATABASE_URL` for remote hosts reached over a network.
    Use a **dedicated database**: on startup the app automatically creates tables and runs migrations (including `ALTER TABLE`, unique index creation, deduplicating `DELETE`s on `target` / `expense_budget`, and duplicate-username renames on `user`), so the role needs `CREATE`, `ALTER`, `INDEX`, and `DELETE` privileges on the `public` schema — never point it at a shared database with same-named tables.

3.  **Build and start** (your own PostgreSQL):
    ```bash
    docker compose up --build        # foreground
    docker compose up --build -d     # detached
    ```

4.  **Verify**: Open `http://localhost:3000` and check `http://localhost:3000/api/health/db` returns `{"status":"ok"}`.

5.  **No PostgreSQL server yet?** Use the bundled one instead:
    ```bash
    docker compose -f docker-compose.yml -f docker-compose.local-db.yml up --build
    ```
    Data persists in the `postgres_data` volume. Bundled-mode commands need the same `-f` flags: stop with `docker compose -f docker-compose.yml -f docker-compose.local-db.yml down`, or delete the volume with `docker compose -f docker-compose.yml -f docker-compose.local-db.yml down -v`. Plain `docker compose down` applies to the default external-DB mode.
    `.env` must still contain a **non-empty** `DATABASE_URL` — compose validates the base file before the override replaces the value with the bundled database's URL. Use alphanumeric `POSTGRES_USER` / `POSTGRES_PASSWORD` values in this mode; the bundled URL is assembled without percent-encoding, so characters like `@ : / # ? %` in the password break it.

**Host PostgreSQL via the Docker bridge (Linux)**: for containers to reach a PostgreSQL running on the host itself, the server must listen on the bridge and accept connections from it. In `postgresql.conf` set `listen_addresses = 'localhost,172.17.0.1'` (avoid `'*'`), in `pg_hba.conf` add a line like `host yourdb dbuser 172.17.0.0/16 scram-sha-256`, use a long random password for the role (it is reachable from every container on the bridge), reload PostgreSQL, and allow port 5432 from the bridge if a firewall is active.

**Note on session cookies over plain HTTP**: outside development mode the app sets `SESSION_COOKIE_SECURE=True`. Browsers accept these cookies on `http://localhost:3000`, but Safari or LAN-IP access over plain HTTP will reject them. For non-localhost HTTP testing in Docker set `APP_ENV=development` in `.env` (containers do not receive `FLASK_ENV`); in production terminate TLS at a reverse proxy.

## Testing

```bash
python -m pytest tests/
```
The test suite always uses an in-memory SQLite database (`sqlite://`) and refuses to run against any other connected database, so it is safe to run locally and in CI.

## Deployment Guide (Koyeb / Railway / Render)

This application is ready to be deployed to modern cloud platforms. It includes a `Procfile` and `requirements.txt` for easy detection by buildpacks.

### Important Note on "Serverless" Free Plans (e.g., Koyeb)
If you received the message: *"Free plan deployments must be serverless. Please go to your service settings and turn on the serverless flag."*
This means your hosting provider (like Koyeb) requires you to use their specific "Serverless" or "Eco" instance type for free tiers. 

**To fix this:**
1. Go to your hosting provider's dashboard (e.g., Koyeb).
2. Navigate to your App / Service settings.
3. Look for the **Instance Type**, **Plan**, or **Regions** section.
4. Select the **Serverless** (or Eco/Free) option and save your changes.
5. Trigger a redeploy.

### General Deployment Steps

1.  **Connect your GitHub repository** to your hosting provider.
2.  **Set Environment Variables** in your provider's dashboard:
    *   `SECRET_KEY`: A strong random string (**required** — the app fails fast in production without it).
    *   `DATABASE_URL`: Your PostgreSQL connection string (e.g., `postgresql://...`) — **required**.
3.  **Build Command**: `pip install -r requirements.txt` (Most platforms detect this automatically).
4.  **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT` (Or rely on the included `Procfile`).
5.  **Deploy!**

### Security Notes

*   **Never hardcode credentials** in `app.py`, templates, tests, or any tracked file. Read them from environment variables only.
*   If credentials were ever committed and pushed, rotate them first (e.g., reset the database password on Railway and change `SECRET_KEY`), then purge them from git history (`git-filter-repo`) and force-push. Deleting the lines is not enough — git history keeps them.
*   Password reset codes are time-limited (30 minutes), expire automatically, and are invalidated after a successful reset or when a newer code is requested.

## Project Structure

*   `app.py`: The main Flask application, routes, and API endpoints.
*   `models.py`: SQLAlchemy database models (`User` and `Transaction`).
*   `templates/index.html`: The single-page frontend application.
*   `requirements.txt`: Python dependencies.
*   `Procfile`: Command to run the web process in production.
*   `Dockerfile`: Container image definition (Python 3.12-slim, non-root, Gunicorn).
*   `docker-compose.yml`: Runs the app connected to your own PostgreSQL (`DATABASE_URL` from `.env`).
*   `docker-compose.local-db.yml`: Opt-in override adding a bundled PostgreSQL with healthcheck.
*   `.dockerignore`: Keeps secrets, virtualenvs, and dev artifacts out of the image.
