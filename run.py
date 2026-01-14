from datetime import datetime
import os

from sqlalchemy import inspect

from app import create_app, db
from app.models import User, AppSetting

def ensure_owner_user():
    owner_username = (os.environ.get('OWNER_USERNAME') or '').strip() or 'admin'
    owner_email = (os.environ.get('OWNER_EMAIL') or '').strip() or 'admin@example.com'
    owner_password = (os.environ.get('OWNER_PASSWORD') or '').strip() or 'admin123'

    user = User.query.filter_by(username=owner_username).first()
    if user is None:
        user = User(username=owner_username, email=owner_email, is_admin=True)
        user.set_password(owner_password)
        db.session.add(user)
        db.session.commit()
        print("Owner user created!")
        return

    changed = False
    if (user.email or '') != owner_email:
        user.email = owner_email
        changed = True
    if not user.is_admin:
        user.is_admin = True
        changed = True
    if owner_password and not user.check_password(owner_password):
        user.set_password(owner_password)
        changed = True
    if changed:
        db.session.commit()
        print("Owner user updated!")
    else:
        print("Owner user already exists.")


def ensure_company_settings() -> None:
    try:
        if not inspect(db.engine).has_table('app_setting'):
            return

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
            'company_logo_path': (os.environ.get('COMPANY_LOGO_PATH') or '').strip() or 'static/img/logo.jpeg',
            'invoice_important_note': (os.environ.get('INVOICE_IMPORTANT_NOTE') or '').strip(),
            'quote_important_note': (os.environ.get('QUOTE_IMPORTANT_NOTE') or '').strip(),
        }

        now = datetime.utcnow()
        for key, val in defaults.items():
            row = AppSetting.query.filter_by(key=key).first()
            if row is None:
                row = AppSetting(key=key, value=val, updated_at=now)
                db.session.add(row)
                continue
            existing = (row.value or '').strip()
            if (not existing) and val:
                row.value = val
                row.updated_at = now

        db.session.commit()
    except Exception:
        db.session.rollback()

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_owner_user()
        ensure_company_settings()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
