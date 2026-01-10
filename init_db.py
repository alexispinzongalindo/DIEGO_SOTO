from app import create_app, db
from app.models import User

def init_db():
    app = create_app()
    with app.app_context():
        # Create all database tables
        db.create_all()
        
        # Create admin user if it doesn't exist
        admin = User.query.filter_by(username='admin').first()
        if admin is None:
            admin = User(username='admin', email='admin@diego-soto.com', is_admin=True)
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("Created admin user with username 'admin' and password 'admin123'")
        
        print("Database initialized successfully!")

if __name__ == '__main__':
    init_db()
