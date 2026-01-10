from datetime import datetime
from time import time
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from flask import current_app
import jwt
from app import db, login_manager

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(512))
    is_admin = db.Column(db.Boolean, default=False)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_reset_password_token(self, expires_in=600):
        return jwt.encode(
            {'reset_password': self.id, 'exp': time() + expires_in},
            current_app.config['SECRET_KEY'],
            algorithm='HS256')

    @staticmethod
    def verify_reset_password_token(token):
        try:
            user_id = jwt.decode(
                token,
                current_app.config['SECRET_KEY'],
                algorithms=['HS256'])['reset_password']
        except Exception:
            return None
        return User.query.get(user_id)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), index=True)
    address = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    tax_id = db.Column(db.String(30))
    credit_limit = db.Column(db.Numeric(10, 2), default=0.00)
    balance = db.Column(db.Numeric(10, 2), default=0.00)
    invoices = db.relationship('Invoice', backref='customer', lazy='dynamic')
    payments = db.relationship('Payment', backref='customer', lazy='dynamic')

class Vendor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), index=True)
    address = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    tax_id = db.Column(db.String(30))
    account_number = db.Column(db.String(30))
    bills = db.relationship('Bill', backref='vendor', lazy='dynamic')
    payments = db.relationship('VendorPayment', backref='vendor', lazy='dynamic')

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, index=True)
    description = db.Column(db.String(200))
    unit = db.Column(db.String(20))
    price = db.Column(db.Numeric(10, 2))
    cost = db.Column(db.Numeric(10, 2))
    quantity_on_hand = db.Column(db.Numeric(10, 2), default=0)
    category = db.Column(db.String(50))

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, index=True)
    date = db.Column(db.Date, index=True, default=datetime.utcnow)
    due_date = db.Column(db.Date)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    subtotal = db.Column(db.Numeric(10, 2))
    tax = db.Column(db.Numeric(10, 2))
    total = db.Column(db.Numeric(10, 2))
    status = db.Column(db.String(20), default='open')  # open, paid, overdue, partial
    terms = db.Column(db.String(50))
    notes = db.Column(db.Text)
    items = db.relationship('InvoiceItem', backref='invoice', lazy='dynamic')
    payments = db.relationship('Payment', backref='invoice', lazy='dynamic')

    @property
    def paid_amount(self):
        return float(sum((p.amount or 0) for p in self.payments))

    @property
    def balance(self):
        return float((self.total or 0) - sum((p.amount or 0) for p in self.payments))

    @property
    def is_overdue(self):
        if not self.due_date:
            return False
        return self.status != 'paid' and self.due_date < datetime.utcnow().date()

class InvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    product = db.relationship('Product')
    description = db.Column(db.String(200))
    quantity = db.Column(db.Numeric(10, 2))
    unit_price = db.Column(db.Numeric(10, 2))
    amount = db.Column(db.Numeric(10, 2))

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, index=True, default=datetime.utcnow)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    amount = db.Column(db.Numeric(10, 2))
    payment_method = db.Column(db.String(50))
    reference = db.Column(db.String(50))
    notes = db.Column(db.Text)

class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, index=True)
    date = db.Column(db.Date, index=True, default=datetime.utcnow)
    due_date = db.Column(db.Date)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'))
    subtotal = db.Column(db.Numeric(10, 2))
    tax = db.Column(db.Numeric(10, 2))
    total = db.Column(db.Numeric(10, 2))
    status = db.Column(db.String(20), default='open')  # open, paid, partial
    terms = db.Column(db.String(50))
    notes = db.Column(db.Text)
    items = db.relationship('BillItem', backref='bill', lazy='dynamic')
    payments = db.relationship('VendorPayment', backref='bill', lazy='dynamic')

    @property
    def paid_amount(self):
        return float(sum((p.amount or 0) for p in self.payments))

    @property
    def balance(self):
        return float((self.total or 0) - sum((p.amount or 0) for p in self.payments))

    @property
    def is_overdue(self):
        if not self.due_date:
            return False
        return self.status != 'paid' and self.due_date < datetime.utcnow().date()

class BillItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bill.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    description = db.Column(db.String(200))
    quantity = db.Column(db.Numeric(10, 2))
    unit_price = db.Column(db.Numeric(10, 2))
    amount = db.Column(db.Numeric(10, 2))

class VendorPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, index=True, default=datetime.utcnow)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'))
    bill_id = db.Column(db.Integer, db.ForeignKey('bill.id'))
    amount = db.Column(db.Numeric(10, 2))
    payment_method = db.Column(db.String(50))
    reference = db.Column(db.String(50))
    notes = db.Column(db.Text)


class Meeting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), index=True)
    start_at = db.Column(db.DateTime, index=True)
    end_at = db.Column(db.DateTime, index=True)
    location = db.Column(db.String(200))
    notes = db.Column(db.Text)
    reminder_minutes = db.Column(db.Integer, default=60)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_by = db.relationship('User')


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    user = db.relationship('User')
    type = db.Column(db.String(50), index=True)
    title = db.Column(db.String(200))
    body = db.Column(db.Text)
    link = db.Column(db.String(255))
    severity = db.Column(db.String(20), default='info')
    ref_type = db.Column(db.String(50), index=True)
    ref_id = db.Column(db.Integer, index=True)
    created_at = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, index=True)

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))
