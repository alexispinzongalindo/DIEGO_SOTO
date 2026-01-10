from flask import render_template
from flask_login import login_required

from app.reports import bp


@bp.route('/ar-aging')
@login_required
def ar_aging():
    return render_template('reports/ar_aging.html', title='A/R Aging')


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
