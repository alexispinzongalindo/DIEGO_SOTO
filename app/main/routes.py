from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.main import bp
from app.models import AppSetting, Invoice, Quote, Bill, Customer, Vendor, Payment, PurchaseOrder, VendorPayment
from datetime import datetime, timedelta


def _get_app_setting(key: str) -> str:
    row = AppSetting.query.filter_by(key=key).first()
    return (row.value or '').strip() if row else ''


def _is_marketing_landing_enabled() -> bool:
    val = _get_app_setting('show_marketing_landing').lower()
    return val in ('1', 'true', 't', 'yes', 'y', 'on')

@bp.route('/')
@bp.route('/index')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    if _is_marketing_landing_enabled():
        return render_template('landing.html', title='Home')
    return render_template('index.html', title='Home')


@bp.route('/landing')
def landing():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    if _is_marketing_landing_enabled():
        return render_template('landing.html', title='Home')
    return render_template('index.html', title='Home')

@bp.route('/dashboard')
@login_required
def dashboard():
    # Get current date and calculate date ranges
    today = datetime.utcnow().date()
    thirty_days_ago = today - timedelta(days=30)
    
    # Get counts for dashboard cards
    customer_count = Customer.query.count()
    vendor_count = Vendor.query.count()
    
    # Get recent invoices and bills
    recent_invoices = Invoice.query.order_by(Invoice.date.desc()).limit(5).all()
    recent_quotes = Quote.query.order_by(Quote.date.desc()).limit(5).all()
    recent_bills = Bill.query.order_by(Bill.date.desc()).limit(5).all()
    recent_purchase_orders = PurchaseOrder.query.order_by(PurchaseOrder.date.desc()).limit(5).all()

    purchase_order_count = PurchaseOrder.query.count()
    draft_po_count = PurchaseOrder.query.filter_by(status='draft').count()
    
    # Calculate total receivables and payables
    total_receivables = db.session.query(db.func.sum(Invoice.total - db.func.coalesce(
        db.session.query(db.func.sum(Payment.amount))
        .filter(Payment.invoice_id == Invoice.id)
        .correlate(Invoice)
        .scalar_subquery(),
        0
    ))).scalar() or 0
    
    total_payables = db.session.query(db.func.sum(Bill.total - db.func.coalesce(
        db.session.query(db.func.sum(VendorPayment.amount))
        .filter(VendorPayment.bill_id == Bill.id)
        .correlate(Bill)
        .scalar_subquery(),
        0
    ))).scalar() or 0
    
    # Calculate 30-day revenue and expenses
    thirty_day_revenue = db.session.query(db.func.sum(Invoice.total))\
        .filter(Invoice.date >= thirty_days_ago).scalar() or 0
    
    thirty_day_expenses = db.session.query(db.func.sum(Bill.total))\
        .filter(Bill.date >= thirty_days_ago).scalar() or 0
    
    # Calculate profit/loss for the last 30 days
    thirty_day_profit = thirty_day_revenue - thirty_day_expenses
    
    return render_template('main/dashboard.html',
                         title='Dashboard',
                         customer_count=customer_count,
                         vendor_count=vendor_count,
                         purchase_order_count=purchase_order_count,
                         draft_po_count=draft_po_count,
                         total_receivables=total_receivables,
                         total_payables=total_payables,
                         thirty_day_revenue=thirty_day_revenue,
                         thirty_day_expenses=thirty_day_expenses,
                         thirty_day_profit=thirty_day_profit,
                         recent_quotes=recent_quotes,
                         recent_invoices=recent_invoices,
                         recent_bills=recent_bills,
                         recent_purchase_orders=recent_purchase_orders,
                         today=today)

@bp.route('/search')
@login_required
def search():
    query = request.args.get('q', '').strip()
    if not query:
        return redirect(url_for('main.dashboard'))
    
    # Search in different models
    customers = Customer.query.filter(
        (Customer.name.ilike(f'%{query}%')) | 
        (Customer.email.ilike(f'%{query}%')) |
        (Customer.phone.ilike(f'%{query}%'))
    ).limit(10).all()
    
    vendors = Vendor.query.filter(
        (Vendor.name.ilike(f'%{query}%')) | 
        (Vendor.email.ilike(f'%{query}%')) |
        (Vendor.phone.ilike(f'%{query}%'))
    ).limit(10).all()
    
    invoices = Invoice.query.filter(
        (Invoice.number.ilike(f'%{query}%')) |
        (Invoice.notes.ilike(f'%{query}%'))
    ).limit(10).all()
    
    bills = Bill.query.filter(
        (Bill.number.ilike(f'%{query}%')) |
        (Bill.notes.ilike(f'%{query}%'))
    ).limit(10).all()
    
    return render_template('main/search_results.html',
                         title=f'Search: {query}',
                         query=query,
                         customers=customers,
                         vendors=vendors,
                         invoices=invoices,
                         bills=bills)

@bp.route('/help')
def help():
    return render_template('main/help.html', title='Help & Support')
