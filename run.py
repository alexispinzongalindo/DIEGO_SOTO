from app import create_app, db
from app.models import User
import os

def create_admin_user():
    admin = User.query.filter_by(username='admin').first()
    if admin is None:
        admin = User(username='admin', email='admin@example.com', is_admin=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("Admin user created!")
    else:
        print("Admin user already exists.")

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_admin_user()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
