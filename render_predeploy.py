from flask_migrate import upgrade

from app import create_app
from run import ensure_owner_user


def main() -> None:
    app = create_app()
    with app.app_context():
        upgrade()
        ensure_owner_user()


if __name__ == '__main__':
    main()
