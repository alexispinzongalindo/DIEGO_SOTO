from datetime import date

from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required

from app import db
from app.accounts_receivable import bp
from app.accounts_receivable.forms import CustomerForm, InvoiceForm, PaymentForm
from app.models import Customer, Invoice, Payment


@bp.route('/invoices')
@login_required
def invoices():
    invoice_list = Invoice.query.order_by(Invoice.date.desc()).all()
    return render_template('ar/invoices.html', title='Invoices', invoices=invoice_list)


@bp.route('/customers')
@login_required
def customers():
    customer_list = Customer.query.order_by(Customer.name.asc()).all()
    return render_template('ar/customers.html', title='Customers', customers=customer_list)


@bp.route('/customers/create', methods=['GET', 'POST'])
@login_required
def create_customer():
    form = CustomerForm()
    if form.validate_on_submit():
        customer = Customer(
            name=form.name.data,
            address=form.address.data,
            phone=form.phone.data,
            email=form.email.data,
            tax_id=form.tax_id.data,
            credit_limit=form.credit_limit.data,
        )
        db.session.add(customer)
        db.session.commit()
        flash('Customer created.', 'success')
        return redirect(url_for('ar.customers'))

    return render_template('ar/create_customer.html', title='Create Customer', form=form)


@bp.route('/payments')
@login_required
def payments():
    payment_list = Payment.query.order_by(Payment.date.desc()).all()
    return render_template('ar/payments.html', title='Payments', payments=payment_list)


@bp.route('/invoice/create', methods=['GET', 'POST'])
@login_required
def create_invoice():
    customers = Customer.query.order_by(Customer.name.asc()).all()
    if not customers:
        flash('Create a customer before creating an invoice.', 'warning')
        return redirect(url_for('ar.create_customer'))

    form = InvoiceForm()
    form.customer_id.choices = [(c.id, c.name) for c in customers]

    if request.method == 'GET':
        form.date.data = date.today()
        if not form.customer_id.data:
            form.customer_id.data = customers[0].id

    if form.validate_on_submit():
        subtotal = form.subtotal.data or 0
        tax = form.tax.data or 0
        total = form.total.data
        if total is None:
            total = subtotal + tax

        invoice = Invoice(
            number=form.number.data,
            date=form.date.data,
            due_date=form.due_date.data,
            customer_id=form.customer_id.data,
            subtotal=subtotal,
            tax=tax,
            total=total,
            status='open',
            terms=form.terms.data,
            notes=form.notes.data,
        )
        db.session.add(invoice)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Unable to create invoice. Make sure the invoice number is unique.', 'danger')
            return render_template('ar/create_invoice.html', title='Create Invoice', form=form)

        flash('Invoice created.', 'success')
        return redirect(url_for('ar.view_invoice', id=invoice.id))

    return render_template('ar/create_invoice.html', title='Create Invoice', form=form)


@bp.route('/payment/record', methods=['GET', 'POST'])
@login_required
def record_payment():
    customers = Customer.query.order_by(Customer.name.asc()).all()
    if not customers:
        flash('Create a customer before recording a payment.', 'warning')
        return redirect(url_for('ar.create_customer'))

    form = PaymentForm()
    form.customer_id.choices = [(c.id, c.name) for c in customers]

    preselect_invoice_id = request.args.get('invoice_id', type=int)
    selected_customer_id = request.args.get('customer_id', type=int)
    if preselect_invoice_id:
        invoice = Invoice.query.get(preselect_invoice_id)
        if invoice:
            selected_customer_id = invoice.customer_id

    if request.method == 'GET':
        form.date.data = date.today()
        if selected_customer_id:
            form.customer_id.data = selected_customer_id
        if not form.customer_id.data:
            form.customer_id.data = customers[0].id
        if preselect_invoice_id:
            form.invoice_id.data = preselect_invoice_id

    invoice_list = Invoice.query.order_by(Invoice.date.desc()).all()
    form.invoice_id.choices = [(0, '-- None --')] + [
        (i.id, f"{i.customer.name if i.customer else ''} - {i.number}") for i in invoice_list
    ]

    if form.validate_on_submit():
        invoice_id = form.invoice_id.data or 0
        if invoice_id == 0:
            invoice_id = None

        if invoice_id:
            invoice = Invoice.query.get(invoice_id)
            if not invoice:
                flash('Selected invoice was not found.', 'danger')
                return render_template('ar/record_payment.html', title='Record Payment', form=form)
            form.customer_id.data = invoice.customer_id

        payment = Payment(
            date=form.date.data,
            customer_id=form.customer_id.data,
            invoice_id=invoice_id,
            amount=form.amount.data,
            payment_method=form.payment_method.data,
            reference=form.reference.data,
            notes=form.notes.data,
        )
        db.session.add(payment)
        db.session.commit()

        if invoice_id:
            invoice = Invoice.query.get(invoice_id)
            if invoice:
                if invoice.balance <= 0.01:
                    invoice.status = 'paid'
                elif invoice.paid_amount > 0:
                    invoice.status = 'partial'
                elif invoice.is_overdue:
                    invoice.status = 'overdue'
                else:
                    invoice.status = 'open'
                db.session.commit()

        flash('Payment recorded.', 'success')
        if invoice_id:
            return redirect(url_for('ar.view_invoice', id=invoice_id))
        return redirect(url_for('ar.payments'))

    return render_template('ar/record_payment.html', title='Record Payment', form=form)


@bp.route('/invoice/<int:id>')
@login_required
def view_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    if invoice.status != 'paid' and invoice.is_overdue and invoice.balance > 0:
        invoice.status = 'overdue'
        db.session.commit()
    payment_list = invoice.payments.order_by(Payment.date.desc()).all()
    return render_template(
        'ar/view_invoice.html',
        title=f'Invoice {invoice.number}',
        invoice=invoice,
        payments=payment_list,
    )
