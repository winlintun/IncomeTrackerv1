from routes.admin import admin_bp
from routes.auth import auth_bp
from routes.expenses import expenses_bp
from routes.income import income_bp
from routes.jobs import jobs_bp
from routes.notes import notes_bp
from routes.pages import pages_bp
from routes.targets import targets_bp


def register_blueprints(app):
    app.register_blueprint(pages_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(income_bp)
    app.register_blueprint(targets_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(admin_bp)
