from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from sqlalchemy import inspect
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
mail = Mail()
migrate = Migrate()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    from app.accounts_receivable import bp as ar_bp
    app.register_blueprint(ar_bp, url_prefix='/ar')

    from app.accounts_payable import bp as ap_bp
    app.register_blueprint(ap_bp, url_prefix='/ap')

    from app.reports import bp as reports_bp
    app.register_blueprint(reports_bp, url_prefix='/reports')

    from app.office import bp as office_bp
    app.register_blueprint(office_bp, url_prefix='/office')

    from app.purchase_orders import bp as po_bp
    app.register_blueprint(po_bp, url_prefix='/po')

    @app.context_processor
    def inject_company_header():
        try:
            if not inspect(db.engine).has_table('app_setting'):
                return {'company_header': {}}
            from app.models import AppSetting
            keys = ['company_name', 'company_address', 'company_phone', 'company_fax', 'company_email', 'company_logo_path']
            rows = AppSetting.query.filter(AppSetting.key.in_(keys)).all()
            vals = {r.key: (r.value or '').strip() for r in rows}
            return {
                'company_header': {
                    'name': vals.get('company_name', ''),
                    'address': vals.get('company_address', ''),
                    'phone': vals.get('company_phone', ''),
                    'fax': vals.get('company_fax', ''),
                    'email': vals.get('company_email', ''),
                    'logo_path': vals.get('company_logo_path', ''),
                }
            }
        except Exception:
            db.session.rollback()
            return {'company_header': {}}

    with app.app_context():
        database_uri = (app.config.get('SQLALCHEMY_DATABASE_URI') or '').strip().lower()
        if database_uri.startswith('sqlite:'):
            db.create_all()

    return app

from app import models
