import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'), override=True)
load_dotenv(os.path.join(basedir, 'app', '.env'), override=True)


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    val = val.strip().lower()
    if val in ('1', 'true', 't', 'yes', 'y', 'on'):
        return True
    if val in ('0', 'false', 'f', 'no', 'n', 'off', ''):
        return False
    return default

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'
    _database_url = os.environ.get('DATABASE_URL')
    if _database_url and _database_url.startswith('postgresql+psycopg2://'):
        _database_url = 'postgresql+psycopg://' + _database_url[len('postgresql+psycopg2://'):]
    if _database_url and _database_url.startswith('postgres://'):
        _database_url = 'postgresql+psycopg://' + _database_url[len('postgres://'):]
    elif _database_url and _database_url.startswith('postgresql://') and '+psycopg' not in _database_url and '+psycopg2' not in _database_url:
        _database_url = 'postgresql+psycopg://' + _database_url[len('postgresql://'):]
    SQLALCHEMY_DATABASE_URI = _database_url or 'sqlite:///' + os.path.join(basedir, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Email configuration
    MAIL_SERVER = (os.environ.get('MAIL_SERVER') or '').strip() or None
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 25)
    MAIL_USE_TLS = _env_bool('MAIL_USE_TLS', default=False)
    MAIL_USE_SSL = _env_bool('MAIL_USE_SSL', default=False)
    MAIL_USERNAME = (os.environ.get('MAIL_USERNAME') or '').strip() or None
    MAIL_PASSWORD = (os.environ.get('MAIL_PASSWORD') or '').strip() or None
    MAIL_DEFAULT_SENDER = (os.environ.get('MAIL_DEFAULT_SENDER') or '').strip() or None
    RESEND_API_KEY = (os.environ.get('RESEND_API_KEY') or '').strip() or None
    RESEND_FROM = (os.environ.get('RESEND_FROM') or '').strip() or None
    RESEND_TIMEOUT = int(os.environ.get('RESEND_TIMEOUT') or 10)
    SENDGRID_API_KEY = (os.environ.get('SENDGRID_API_KEY') or '').strip() or None
    SENDGRID_FROM = (os.environ.get('SENDGRID_FROM') or '').strip() or None
    SENDGRID_TIMEOUT = int(os.environ.get('SENDGRID_TIMEOUT') or 10)
    MAIL_TIMEOUT = int(os.environ.get('MAIL_TIMEOUT') or 10)
    ADMINS = [os.environ.get('ADMIN_EMAIL') or 'admin@example.com']
    
    # Items per page for pagination
    ITEMS_PER_PAGE = 25
    
    # File upload configuration
    UPLOAD_FOLDER = os.path.join(basedir, 'app/static/uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif'}
    
    # Report configuration
    REPORTS_FOLDER = os.path.join(basedir, 'app/static/reports')

    # OpenAI assistant configuration
    OPENAI_API_KEY = (os.environ.get('OPENAI_API_KEY') or '').strip() or None
    OPENAI_MODEL = (os.environ.get('OPENAI_MODEL') or 'gpt-4o-mini').strip()
    OPENAI_TIMEOUT = int(os.environ.get('OPENAI_TIMEOUT') or 15)
    OPENAI_MAX_TOKENS = int(os.environ.get('OPENAI_MAX_TOKENS') or 250)
