from flask_migrate import upgrade
from sqlalchemy import text

from app import create_app, db
from run import ensure_owner_user, ensure_company_settings


def main() -> None:
    app = create_app()
    with app.app_context():
        upgrade(directory='migrations')
        try:
            if db.engine.dialect.name == 'postgresql':
                db.session.execute(text('ALTER TABLE app_setting ALTER COLUMN value TYPE TEXT'))
                db.session.commit()
        except Exception:
            db.session.rollback()
        ensure_owner_user()
        ensure_company_settings()


if __name__ == '__main__':
    main()
