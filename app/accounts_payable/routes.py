from flask import render_template
from flask_login import login_required

from app.accounts_payable import bp


@bp.route('/bills')
@login_required
def bills():
    return render_template('ap/bills.html', title='Bills')


@bp.route('/vendors')
@login_required
def vendors():
    return render_template('ap/vendors.html', title='Vendors')


@bp.route('/payments')
@login_required
def payments():
    return render_template('ap/payments.html', title='Payments')


@bp.route('/bill/create')
@login_required
def create_bill():
    return render_template('ap/create_bill.html', title='Create Bill')


@bp.route('/payment/record')
@login_required
def record_payment():
    return render_template('ap/record_payment.html', title='Pay Bill')


@bp.route('/bill/<int:id>')
@login_required
def view_bill(id):
    return render_template('ap/view_bill.html', title=f'Bill {id}', bill_id=id)
