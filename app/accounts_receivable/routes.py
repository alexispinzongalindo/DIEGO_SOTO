from flask import render_template
from flask_login import login_required

from app.accounts_receivable import bp


@bp.route('/invoices')
@login_required
def invoices():
    return render_template('ar/invoices.html', title='Invoices')


@bp.route('/customers')
@login_required
def customers():
    return render_template('ar/customers.html', title='Customers')


@bp.route('/payments')
@login_required
def payments():
    return render_template('ar/payments.html', title='Payments')


@bp.route('/invoice/create')
@login_required
def create_invoice():
    return render_template('ar/create_invoice.html', title='Create Invoice')


@bp.route('/payment/record')
@login_required
def record_payment():
    return render_template('ar/record_payment.html', title='Record Payment')


@bp.route('/invoice/<int:id>')
@login_required
def view_invoice(id):
    return render_template('ar/view_invoice.html', title=f'Invoice {id}', invoice_id=id)
