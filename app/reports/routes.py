from datetime import date

from flask import render_template
from flask_login import login_required

from app.reports import bp
from app.models import Invoice


@bp.route('/ar-aging')
@login_required
def ar_aging():
    today = date.today()
    open_invoices = Invoice.query.all()

    buckets = {
        'current': 0.0,
        '1_30': 0.0,
        '31_60': 0.0,
        '61_90': 0.0,
        '90_plus': 0.0,
        'total': 0.0,
    }

    by_customer = {}

    for inv in open_invoices:
        balance = float(inv.balance or 0)
        if balance <= 0.01:
            continue

        due = inv.due_date or inv.date
        days_past_due = (today - due).days if due else 0

        if days_past_due <= 0:
            bucket_key = 'current'
        elif days_past_due <= 30:
            bucket_key = '1_30'
        elif days_past_due <= 60:
            bucket_key = '31_60'
        elif days_past_due <= 90:
            bucket_key = '61_90'
        else:
            bucket_key = '90_plus'

        buckets[bucket_key] += balance
        buckets['total'] += balance

        customer = inv.customer
        customer_key = customer.id if customer else inv.customer_id
        if customer_key not in by_customer:
            by_customer[customer_key] = {
                'customer': customer,
                'current': 0.0,
                '1_30': 0.0,
                '31_60': 0.0,
                '61_90': 0.0,
                '90_plus': 0.0,
                'total': 0.0,
            }

        by_customer[customer_key][bucket_key] += balance
        by_customer[customer_key]['total'] += balance

    customer_rows = sorted(
        by_customer.values(),
        key=lambda r: (r['customer'].name.lower() if r['customer'] and r['customer'].name else '')
    )

    return render_template(
        'reports/ar_aging.html',
        title='A/R Aging',
        today=today,
        buckets=buckets,
        customer_rows=customer_rows,
    )


@bp.route('/ap-aging')
@login_required
def ap_aging():
    return render_template('reports/ap_aging.html', title='A/P Aging')


@bp.route('/profit-loss')
@login_required
def profit_loss():
    return render_template('reports/profit_loss.html', title='Profit & Loss')


@bp.route('/balance-sheet')
@login_required
def balance_sheet():
    return render_template('reports/balance_sheet.html', title='Balance Sheet')


@bp.route('/sales-by-customer')
@login_required
def sales_by_customer():
    return render_template('reports/sales_by_customer.html', title='Sales by Customer')


@bp.route('/sales-by-product')
@login_required
def sales_by_product():
    return render_template('reports/sales_by_product.html', title='Sales by Product')
