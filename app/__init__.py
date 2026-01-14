from flask import Flask
import os
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from sqlalchemy import inspect
from config import Config
from decimal import Decimal

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
mail = Mail()
migrate = Migrate()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    @app.template_filter('money')
    def money_filter(value, places=2):
        try:
            n = Decimal(str(value or 0))
            p = int(places)
            if p < 0:
                p = 0
            return f"{n:,.{p}f}"
        except Exception:
            return "0.00" if int(places or 0) == 2 else "0"

    @app.template_filter('num')
    def num_filter(value, places=0):
        try:
            n = Decimal(str(value or 0))
            p = int(places)
            if p < 0:
                p = 0
            return f"{n:,.{p}f}"
        except Exception:
            return "0"

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
            defaults = {
                'company_name': (os.environ.get('COMPANY_NAME') or '').strip() or 'Diego Soto & Associates',
                'company_address': (os.environ.get('COMPANY_ADDRESS') or '').strip(),
                'company_phone': (os.environ.get('COMPANY_PHONE') or '').strip(),
                'company_phone_1': (os.environ.get('COMPANY_PHONE_1') or '').strip(),
                'company_phone_2': (os.environ.get('COMPANY_PHONE_2') or '').strip(),
                'company_phone_3': (os.environ.get('COMPANY_PHONE_3') or '').strip(),
                'company_fax': (os.environ.get('COMPANY_FAX') or '').strip(),
                'company_email': (os.environ.get('COMPANY_EMAIL') or '').strip(),
                'company_email_1': (os.environ.get('COMPANY_EMAIL_1') or '').strip(),
                'company_email_2': (os.environ.get('COMPANY_EMAIL_2') or '').strip(),
                'company_email_3': (os.environ.get('COMPANY_EMAIL_3') or '').strip(),
                'company_logo_path': (os.environ.get('COMPANY_LOGO_PATH') or '').strip() or 'static/img/logo.png',
            }

            if not inspect(db.engine).has_table('app_setting'):
                return {
                    'company_header': {
                        'name': defaults.get('company_name', ''),
                        'address': defaults.get('company_address', ''),
                        'phone': defaults.get('company_phone', ''),
                        'phone_1': defaults.get('company_phone_1', ''),
                        'phone_2': defaults.get('company_phone_2', ''),
                        'phone_3': defaults.get('company_phone_3', ''),
                        'fax': defaults.get('company_fax', ''),
                        'email': defaults.get('company_email', ''),
                        'email_1': defaults.get('company_email_1', ''),
                        'email_2': defaults.get('company_email_2', ''),
                        'email_3': defaults.get('company_email_3', ''),
                        'logo_path': defaults.get('company_logo_path', ''),
                    }
                }
            from app.models import AppSetting
            keys = [
                'company_name', 'company_address',
                'company_phone', 'company_phone_1', 'company_phone_2', 'company_phone_3',
                'company_fax',
                'company_email', 'company_email_1', 'company_email_2', 'company_email_3',
                'company_logo_path',
            ]
            rows = AppSetting.query.filter(AppSetting.key.in_(keys)).all()
            vals = {r.key: (r.value or '').strip() for r in rows}

            def _pick(key: str) -> str:
                v = (vals.get(key) or '').strip()
                if v:
                    return v
                return (defaults.get(key) or '').strip()

            return {
                'company_header': {
                    'name': _pick('company_name'),
                    'address': _pick('company_address'),
                    'phone': _pick('company_phone'),
                    'phone_1': _pick('company_phone_1'),
                    'phone_2': _pick('company_phone_2'),
                    'phone_3': _pick('company_phone_3'),
                    'fax': _pick('company_fax'),
                    'email': _pick('company_email'),
                    'email_1': _pick('company_email_1'),
                    'email_2': _pick('company_email_2'),
                    'email_3': _pick('company_email_3'),
                    'logo_path': _pick('company_logo_path'),
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
