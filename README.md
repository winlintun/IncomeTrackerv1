# Income Tracker

A full-stack web application built with Flask and PostgreSQL to help users track their income and expenses. It features user authentication, role-based access control (with a single-admin enforcement), and a responsive UI.

## Features

*   **User Authentication**: Secure registration and login using `Flask-Login` and `Flask-Bcrypt`.
*   **Dashboard**: View total income, total expenses, and net balance.
*   **Transaction Management**: Add, edit, and delete income and expense records.
*   **Admin Panel**: A dedicated dashboard for the admin to view all users and manage their roles.
*   **Single Admin Rule**: The system strictly enforces that only one user can hold the `admin` role at any given time.
*   **PostgreSQL Database**: Robust data storage using PostgreSQL and `Flask-SQLAlchemy`.

## Tech Stack

*   **Backend**: Python, Flask, Flask-SQLAlchemy, Flask-Login, Flask-Bcrypt
*   **Database**: PostgreSQL
*   **Frontend**: HTML, JavaScript, Tailwind CSS (via CDN)
*   **Server**: Gunicorn (for production)

## Local Development Setup

1.  **Clone the repository** (if you haven't already):
    ```bash
    git clone <your-repository-url>
    cd income-tracker
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
    Create a `.env` file in the root directory and add your configuration:
    ```env
    SECRET_KEY=your_super_secret_key_here
    DATABASE_URL=postgresql://user:password@localhost:5432/yourdb
    ```
    *(Note: The app is currently configured to use a remote PostgreSQL database. If you want to use a local one, update the `DATABASE_URL` accordingly).*

5.  **Run the application**:
    ```bash
    python app.py
    ```
    The app will be available at `http://localhost:3000`.

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
    *   `SECRET_KEY`: A strong random string.
    *   `DATABASE_URL`: Your PostgreSQL connection string (e.g., `postgresql://...`).
3.  **Build Command**: `pip install -r requirements.txt` (Most platforms detect this automatically).
4.  **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT` (Or rely on the included `Procfile`).
5.  **Deploy!**

## Project Structure

*   `app.py`: The main Flask application, routes, and API endpoints.
*   `models.py`: SQLAlchemy database models (`User` and `Transaction`).
*   `templates/index.html`: The single-page frontend application.
*   `requirements.txt`: Python dependencies.
*   `Procfile`: Command to run the web process in production.
