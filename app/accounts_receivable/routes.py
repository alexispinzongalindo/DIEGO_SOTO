from datetime import date
from io import BytesIO

from flask import render_template, redirect, url_for, flash, request, send_file, current_app
from flask_login import login_required
from fpdf import FPDF

from app import db
from app.accounts_receivable import bp
from app.accounts_receivable.forms import CustomerForm, InvoiceForm, QuoteForm, PaymentForm, EmailInvoiceForm, ItemForm, DeleteForm
from app.auth.email import send_email_with_attachments_sync
from app.models import Customer, Invoice, Quote, Payment, InvoiceItem, QuoteItem, Product


def _build_invoice_pdf(invoice, items):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, 'Invoice', ln=True)

    pdf.set_font('Helvetica', '', 11)
    pdf.cell(0, 6, f"Invoice #: {invoice.number}", ln=True)
    pdf.cell(0, 6, f"Invoice Date: {invoice.date.strftime('%Y-%m-%d') if invoice.date else ''}", ln=True)
    pdf.cell(0, 6, f"Due Date: {invoice.due_date.strftime('%Y-%m-%d') if invoice.due_date else ''}", ln=True)
    if invoice.customer:
        pdf.cell(0, 6, f"Customer: {invoice.customer.name}", ln=True)
    pdf.ln(4)

    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(90, 8, 'Description', border=1)
    pdf.cell(20, 8, 'Qty', border=1, align='R')
    pdf.cell(30, 8, 'Unit Price', border=1, align='R')
    pdf.cell(30, 8, 'Amount', border=1, align='R')
    pdf.ln(8)

    pdf.set_font('Helvetica', '', 10)
    for item in items:
        desc = item.description or (item.product.description if item.product else '')
        qty = float(item.quantity or 0)
        unit_price = float(item.unit_price or 0)
        amount = float(item.amount or 0)
        pdf.cell(90, 8, (desc[:45] + '...') if len(desc) > 48 else desc, border=1)
        pdf.cell(20, 8, f"{qty:g}", border=1, align='R')
        pdf.cell(30, 8, f"${unit_price:,.2f}", border=1, align='R')
        pdf.cell(30, 8, f"${amount:,.2f}", border=1, align='R')
        pdf.ln(8)

    pdf.ln(4)
    pdf.set_font('Helvetica', '', 11)
    subtotal = float(invoice.subtotal or 0)
    tax = float(invoice.tax or 0)
    total = float(invoice.total or 0)
    pdf.cell(140, 6, 'Subtotal', align='R')
    pdf.cell(30, 6, f"${subtotal:,.2f}", ln=True, align='R')
    pdf.cell(140, 6, 'Tax', align='R')
    pdf.cell(30, 6, f"${tax:,.2f}", ln=True, align='R')
    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(140, 7, 'Total', align='R')
    pdf.cell(30, 7, f"${total:,.2f}", ln=True, align='R')

    out = pdf.output(dest='S')
    if isinstance(out, str):
        out = out.encode('latin-1')
    return out


def _next_quote_number():
    last = Quote.query.order_by(Quote.id.desc()).first()
    if not last or not last.number:
        return 'Q-000001'
    try:
        raw = (last.number or '').strip().upper()
        if raw.startswith('Q-'):
            n = int(raw.split('-', 1)[1])
        else:
            n = int(raw)
        return f"Q-{n + 1:06d}"
    except Exception:
        return f"Q-{(last.id + 1):06d}"


def _next_invoice_number():
    last = Invoice.query.order_by(Invoice.id.desc()).first()
    if not last or not last.number:
        return 'INV-000001'
    try:
        raw = (last.number or '').strip().upper()
        if raw.startswith('INV-'):
            n = int(raw.split('-', 1)[1])
        else:
            n = int(raw)
        return f"INV-{n + 1:06d}"
    except Exception:
        return f"INV-{(last.id + 1):06d}"


@bp.route('/invoices')
@login_required
def invoices():
    invoice_list = Invoice.query.order_by(Invoice.date.desc()).all()
    delete_form = DeleteForm()
    return render_template('ar/invoices.html', title='Invoices', invoices=invoice_list, delete_form=delete_form)


@bp.route('/quotes')
@login_required
def quotes():
    quote_list = Quote.query.order_by(Quote.date.desc()).all()
    delete_form = DeleteForm()
    return render_template('ar/quotes.html', title='Quotes', quotes=quote_list, delete_form=delete_form)


@bp.route('/customers')
@login_required
def customers():
    customer_list = Customer.query.order_by(Customer.name.asc()).all()
    return render_template('ar/customers.html', title='Customers', customers=customer_list)


@bp.route('/customers/<int:id>')
@login_required
def view_customer(id):
    customer = Customer.query.get_or_404(id)
    invoice_list = customer.invoices.order_by(Invoice.date.desc()).all()
    payment_list = customer.payments.order_by(Payment.date.desc()).all()
    return render_template(
        'ar/view_customer.html',
        title=f'Customer {customer.name}',
        customer=customer,
        invoices=invoice_list,
        payments=payment_list,
    )


@bp.route('/customers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_customer(id):
    customer = Customer.query.get_or_404(id)
    form = CustomerForm(obj=customer)
    if form.validate_on_submit():
        customer.name = form.name.data
        customer.address = form.address.data
        customer.phone = form.phone.data
        customer.email = form.email.data
        customer.tax_id = form.tax_id.data
        customer.credit_limit = form.credit_limit.data
        db.session.commit()
        flash('Customer updated.', 'success')
        return redirect(url_for('ar.view_customer', id=customer.id))

    return render_template('ar/edit_customer.html', title=f'Edit Customer {customer.name}', form=form, customer=customer)


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


@bp.route('/items')
@login_required
def items():
    item_list = Product.query.order_by(Product.code.asc()).all()
    return render_template('ar/items.html', title='Items', items=item_list)


@bp.route('/items/create', methods=['GET', 'POST'])
@login_required
def create_item():
    form = ItemForm()
    if form.validate_on_submit():
        item = Product(
            code=(form.code.data or '').strip() or None,
            description=(form.description.data or '').strip(),
            price=form.price.data,
        )
        db.session.add(item)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Unable to create item. Make sure the code is unique.', 'danger')
            return render_template('ar/create_item.html', title='Create Item', form=form)

        flash('Item created.', 'success')
        next_url = request.args.get('next')
        if next_url and next_url.startswith('/'):
            return redirect(next_url)
        return redirect(url_for('ar.items'))

    return render_template('ar/create_item.html', title='Create Item', form=form)


@bp.route('/invoice/create', methods=['GET', 'POST'])
@login_required
def create_invoice():
    customers = Customer.query.order_by(Customer.name.asc()).all()
    if not customers:
        flash('Create a customer before creating an invoice.', 'warning')
        return redirect(url_for('ar.create_customer'))

    products = Product.query.order_by(Product.code.asc()).all()
    product_choices = [(0, '-- Select --')] + [(p.id, f"{p.code} - {p.description}") for p in products]

    form = InvoiceForm()
    form.customer_id.choices = [(c.id, c.name) for c in customers]

    for item_form in form.items:
        item_form.form.product_id.choices = product_choices

    if request.method == 'GET':
        form.date.data = date.today()
        if not form.customer_id.data:
            form.customer_id.data = customers[0].id

    if form.validate_on_submit():
        item_rows = []
        subtotal = 0.0
        for item_form in form.items:
            product_id = item_form.form.product_id.data or 0
            if product_id == 0:
                product_id = None

            description = (item_form.form.description.data or '').strip()
            qty = item_form.form.quantity.data
            unit_price = item_form.form.unit_price.data

            is_blank = (not product_id) and (not description) and (qty is None) and (unit_price is None)
            if is_blank:
                continue

            product = Product.query.get(product_id) if product_id else None
            if not description and product:
                description = product.description or ''

            if qty is None:
                flash('Each invoice item must include a quantity.', 'danger')
                return render_template('ar/create_invoice.html', title='Create Invoice', form=form)

            if unit_price is None and product:
                unit_price = product.price
            if unit_price is None:
                flash('Each invoice item must include a unit price (or select an item with a default price).', 'danger')
                return render_template('ar/create_invoice.html', title='Create Invoice', form=form)

            amount = float(qty) * float(unit_price)
            subtotal += amount
            item_rows.append({
                'product': product,
                'product_id': product_id,
                'description': description,
                'quantity': qty,
                'unit_price': unit_price,
                'amount': amount,
            })

        if not item_rows:
            flash('Add at least one invoice item.', 'danger')
            return render_template('ar/create_invoice.html', title='Create Invoice', form=form)

        tax = float(form.tax.data or 0)
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

        for row in item_rows:
            inv_item = InvoiceItem(
                invoice=invoice,
                product_id=row['product_id'],
                description=row['description'],
                quantity=row['quantity'],
                unit_price=row['unit_price'],
                amount=row['amount'],
            )
            db.session.add(inv_item)

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Unable to create invoice. Make sure the invoice number is unique.', 'danger')
            return render_template('ar/create_invoice.html', title='Create Invoice', form=form)

        flash('Invoice created.', 'success')
        return redirect(url_for('ar.view_invoice', id=invoice.id))

    return render_template('ar/create_invoice.html', title='Create Invoice', form=form)


@bp.route('/quote/create', methods=['GET', 'POST'])
@login_required
def create_quote():
    customers = Customer.query.order_by(Customer.name.asc()).all()
    if not customers:
        flash('Create a customer before creating a quote.', 'warning')
        return redirect(url_for('ar.create_customer'))

    products = Product.query.order_by(Product.code.asc()).all()
    product_choices = [(0, '-- Select --')] + [(p.id, f"{p.code} - {p.description}") for p in products]

    form = QuoteForm()
    form.customer_id.choices = [(c.id, c.name) for c in customers]
    for item_form in form.items:
        item_form.form.product_id.choices = product_choices

    if request.method == 'GET':
        form.date.data = date.today()
        form.status.data = 'draft'
        if not form.customer_id.data:
            form.customer_id.data = customers[0].id

    if form.validate_on_submit():
        item_rows = []
        subtotal = 0.0
        for item_form in form.items:
            product_id = item_form.form.product_id.data or 0
            if product_id == 0:
                product_id = None

            description = (item_form.form.description.data or '').strip()
            qty = item_form.form.quantity.data
            unit_price = item_form.form.unit_price.data

            is_blank = (not product_id) and (not description) and (qty is None) and (unit_price is None)
            if is_blank:
                continue

            product = Product.query.get(product_id) if product_id else None
            if not description and product:
                description = product.description or ''

            if qty is None:
                flash('Each quote item must include a quantity.', 'danger')
                return render_template('ar/create_quote.html', title='Create Quote', form=form)

            if unit_price is None and product:
                unit_price = product.price
            if unit_price is None:
                flash('Each quote item must include a unit price (or select an item with a default price).', 'danger')
                return render_template('ar/create_quote.html', title='Create Quote', form=form)

            amount = float(qty) * float(unit_price)
            subtotal += amount
            item_rows.append({
                'product_id': product_id,
                'description': description,
                'quantity': qty,
                'unit_price': unit_price,
                'amount': amount,
            })

        if not item_rows:
            flash('Add at least one quote item.', 'danger')
            return render_template('ar/create_quote.html', title='Create Quote', form=form)

        tax = float(form.tax.data or 0)
        total = subtotal + tax
        quote = Quote(
            number=_next_quote_number(),
            date=form.date.data,
            valid_until=form.valid_until.data,
            customer_id=form.customer_id.data,
            subtotal=subtotal,
            tax=tax,
            total=total,
            status=form.status.data,
            terms=form.terms.data,
            notes=form.notes.data,
        )
        db.session.add(quote)

        for row in item_rows:
            q_item = QuoteItem(
                quote=quote,
                product_id=row['product_id'],
                description=row['description'],
                quantity=row['quantity'],
                unit_price=row['unit_price'],
                amount=row['amount'],
            )
            db.session.add(q_item)

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Unable to create quote.', 'danger')
            return render_template('ar/create_quote.html', title='Create Quote', form=form)

        flash('Quote created.', 'success')
        return redirect(url_for('ar.view_quote', id=quote.id))

    return render_template('ar/create_quote.html', title='Create Quote', form=form)


@bp.route('/quote/<int:id>')
@login_required
def view_quote(id):
    quote = Quote.query.get_or_404(id)
    item_list = quote.items.order_by(QuoteItem.id.asc()).all()
    delete_form = DeleteForm()
    return render_template(
        'ar/view_quote.html',
        title=f'Quote {quote.number}',
        quote=quote,
        items=item_list,
        delete_form=delete_form,
    )


@bp.route('/quote/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_quote(id):
    quote = Quote.query.get_or_404(id)

    customers = Customer.query.order_by(Customer.name.asc()).all()
    if not customers:
        flash('Create a customer before editing a quote.', 'warning')
        return redirect(url_for('ar.create_customer'))

    products = Product.query.order_by(Product.code.asc()).all()
    product_choices = [(0, '-- Select --')] + [(p.id, f"{p.code} - {p.description}") for p in products]

    form = QuoteForm(obj=quote)
    form.submit.label.text = 'Save Quote'
    form.customer_id.choices = [(c.id, c.name) for c in customers]
    for item_form in form.items:
        item_form.form.product_id.choices = product_choices

    if request.method == 'GET':
        form.customer_id.data = quote.customer_id
        existing_items = quote.items.order_by(QuoteItem.id.asc()).all()
        for idx, q_item in enumerate(existing_items[: len(form.items)]):
            form.items[idx].form.product_id.data = q_item.product_id or 0
            form.items[idx].form.description.data = q_item.description
            form.items[idx].form.quantity.data = q_item.quantity
            form.items[idx].form.unit_price.data = q_item.unit_price

    if form.validate_on_submit():
        item_rows = []
        subtotal = 0.0
        for item_form in form.items:
            product_id = item_form.form.product_id.data or 0
            if product_id == 0:
                product_id = None

            description = (item_form.form.description.data or '').strip()
            qty = item_form.form.quantity.data
            unit_price = item_form.form.unit_price.data

            is_blank = (not product_id) and (not description) and (qty is None) and (unit_price is None)
            if is_blank:
                continue

            product = Product.query.get(product_id) if product_id else None
            if not description and product:
                description = product.description or ''

            if qty is None:
                flash('Each quote item must include a quantity.', 'danger')
                return render_template('ar/edit_quote.html', title=f'Edit Quote {quote.number}', form=form, quote=quote)

            if unit_price is None and product:
                unit_price = product.price
            if unit_price is None:
                flash('Each quote item must include a unit price (or select an item with a default price).', 'danger')
                return render_template('ar/edit_quote.html', title=f'Edit Quote {quote.number}', form=form, quote=quote)

            amount = float(qty) * float(unit_price)
            subtotal += amount
            item_rows.append({
                'product_id': product_id,
                'description': description,
                'quantity': qty,
                'unit_price': unit_price,
                'amount': amount,
            })

        if not item_rows:
            flash('Add at least one quote item.', 'danger')
            return render_template('ar/edit_quote.html', title=f'Edit Quote {quote.number}', form=form, quote=quote)

        tax = float(form.tax.data or 0)
        total = subtotal + tax

        quote.date = form.date.data
        quote.valid_until = form.valid_until.data
        quote.customer_id = form.customer_id.data
        quote.subtotal = subtotal
        quote.tax = tax
        quote.total = total
        quote.status = form.status.data
        quote.terms = form.terms.data
        quote.notes = form.notes.data

        existing_items = quote.items.all()
        for q_item in existing_items:
            db.session.delete(q_item)
        db.session.flush()

        for row in item_rows:
            q_item = QuoteItem(
                quote=quote,
                product_id=row['product_id'],
                description=row['description'],
                quantity=row['quantity'],
                unit_price=row['unit_price'],
                amount=row['amount'],
            )
            db.session.add(q_item)

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Unable to update quote.', 'danger')
            return render_template('ar/edit_quote.html', title=f'Edit Quote {quote.number}', form=form, quote=quote)

        flash('Quote updated.', 'success')
        return redirect(url_for('ar.view_quote', id=quote.id))

    return render_template('ar/edit_quote.html', title=f'Edit Quote {quote.number}', form=form, quote=quote)


@bp.route('/quote/<int:id>/delete', methods=['POST'])
@login_required
def delete_quote(id):
    quote = Quote.query.get_or_404(id)
    form = DeleteForm()
    if not form.validate_on_submit():
        flash('Unable to delete quote.', 'danger')
        return redirect(url_for('ar.view_quote', id=quote.id))

    if quote.invoice_id:
        flash('Cannot delete a quote that has been invoiced.', 'warning')
        return redirect(url_for('ar.view_quote', id=quote.id))

    items = quote.items.all()
    for q_item in items:
        db.session.delete(q_item)
    db.session.delete(quote)
    db.session.commit()
    flash('Quote deleted.', 'success')
    return redirect(url_for('ar.quotes'))


@bp.route('/quote/<int:id>/convert', methods=['POST'])
@login_required
def convert_quote_to_invoice(id):
    quote = Quote.query.get_or_404(id)
    form = DeleteForm()
    if not form.validate_on_submit():
        flash('Unable to convert quote.', 'danger')
        return redirect(url_for('ar.view_quote', id=quote.id))

    if quote.invoice_id:
        flash('Quote has already been converted to an invoice.', 'warning')
        return redirect(url_for('ar.view_invoice', id=quote.invoice_id))

    item_list = quote.items.order_by(QuoteItem.id.asc()).all()
    if not item_list:
        flash('Cannot convert a quote with no items.', 'danger')
        return redirect(url_for('ar.view_quote', id=quote.id))

    invoice = Invoice(
        number=_next_invoice_number(),
        date=date.today(),
        due_date=None,
        customer_id=quote.customer_id,
        subtotal=quote.subtotal,
        tax=quote.tax,
        total=quote.total,
        status='open',
        terms=quote.terms,
        notes=quote.notes,
    )
    db.session.add(invoice)

    for q_item in item_list:
        inv_item = InvoiceItem(
            invoice=invoice,
            product_id=q_item.product_id,
            description=q_item.description,
            quantity=q_item.quantity,
            unit_price=q_item.unit_price,
            amount=q_item.amount,
        )
        db.session.add(inv_item)

    quote.invoice = invoice
    quote.status = 'invoiced'

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('Unable to convert quote to invoice.', 'danger')
        return redirect(url_for('ar.view_quote', id=quote.id))

    flash('Quote converted to invoice.', 'success')
    return redirect(url_for('ar.view_invoice', id=invoice.id))


@bp.route('/invoice/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_invoice(id):
    invoice = Invoice.query.get_or_404(id)

    customers = Customer.query.order_by(Customer.name.asc()).all()
    if not customers:
        flash('Create a customer before editing an invoice.', 'warning')
        return redirect(url_for('ar.create_customer'))

    products = Product.query.order_by(Product.code.asc()).all()
    product_choices = [(0, '-- Select --')] + [(p.id, f"{p.code} - {p.description}") for p in products]

    form = InvoiceForm(obj=invoice)
    form.submit.label.text = 'Save Invoice'
    form.customer_id.choices = [(c.id, c.name) for c in customers]

    for item_form in form.items:
        item_form.form.product_id.choices = product_choices

    if request.method == 'GET':
        form.customer_id.data = invoice.customer_id
        existing_items = invoice.items.order_by(InvoiceItem.id.asc()).all()
        for idx, inv_item in enumerate(existing_items[: len(form.items)]):
            form.items[idx].form.product_id.data = inv_item.product_id or 0
            form.items[idx].form.description.data = inv_item.description
            form.items[idx].form.quantity.data = inv_item.quantity
            form.items[idx].form.unit_price.data = inv_item.unit_price

    if form.validate_on_submit():
        item_rows = []
        subtotal = 0.0
        for item_form in form.items:
            product_id = item_form.form.product_id.data or 0
            if product_id == 0:
                product_id = None

            description = (item_form.form.description.data or '').strip()
            qty = item_form.form.quantity.data
            unit_price = item_form.form.unit_price.data

            is_blank = (not product_id) and (not description) and (qty is None) and (unit_price is None)
            if is_blank:
                continue

            product = Product.query.get(product_id) if product_id else None
            if not description and product:
                description = product.description or ''

            if qty is None:
                flash('Each invoice item must include a quantity.', 'danger')
                return render_template('ar/edit_invoice.html', title=f'Edit Invoice {invoice.number}', form=form, invoice=invoice)

            if unit_price is None and product:
                unit_price = product.price
            if unit_price is None:
                flash('Each invoice item must include a unit price (or select an item with a default price).', 'danger')
                return render_template('ar/edit_invoice.html', title=f'Edit Invoice {invoice.number}', form=form, invoice=invoice)

            amount = float(qty) * float(unit_price)
            subtotal += amount
            item_rows.append({
                'product_id': product_id,
                'description': description,
                'quantity': qty,
                'unit_price': unit_price,
                'amount': amount,
            })

        if not item_rows:
            flash('Add at least one invoice item.', 'danger')
            return render_template('ar/edit_invoice.html', title=f'Edit Invoice {invoice.number}', form=form, invoice=invoice)

        tax = float(form.tax.data or 0)
        total = subtotal + tax

        invoice.number = form.number.data
        invoice.date = form.date.data
        invoice.due_date = form.due_date.data
        invoice.customer_id = form.customer_id.data
        invoice.subtotal = subtotal
        invoice.tax = tax
        invoice.total = total
        invoice.terms = form.terms.data
        invoice.notes = form.notes.data

        existing_items = invoice.items.all()
        for inv_item in existing_items:
            db.session.delete(inv_item)
        db.session.flush()

        for row in item_rows:
            inv_item = InvoiceItem(
                invoice=invoice,
                product_id=row['product_id'],
                description=row['description'],
                quantity=row['quantity'],
                unit_price=row['unit_price'],
                amount=row['amount'],
            )
            db.session.add(inv_item)

        if invoice.balance <= 0.01:
            invoice.status = 'paid'
        elif invoice.paid_amount > 0:
            invoice.status = 'partial'
        elif invoice.is_overdue and invoice.balance > 0:
            invoice.status = 'overdue'
        else:
            invoice.status = 'open'

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Unable to update invoice. Make sure the invoice number is unique.', 'danger')
            return render_template('ar/edit_invoice.html', title=f'Edit Invoice {invoice.number}', form=form, invoice=invoice)

        flash('Invoice updated.', 'success')
        return redirect(url_for('ar.view_invoice', id=invoice.id))

    return render_template('ar/edit_invoice.html', title=f'Edit Invoice {invoice.number}', form=form, invoice=invoice)


@bp.route('/invoice/<int:id>/delete', methods=['POST'])
@login_required
def delete_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    form = DeleteForm()
    if not form.validate_on_submit():
        flash('Unable to delete invoice.', 'danger')
        return redirect(url_for('ar.view_invoice', id=invoice.id))

    if invoice.payments.count() > 0:
        flash('Cannot delete an invoice that has payments recorded.', 'warning')
        return redirect(url_for('ar.view_invoice', id=invoice.id))

    items = invoice.items.all()
    for inv_item in items:
        db.session.delete(inv_item)
    db.session.delete(invoice)
    db.session.commit()
    flash('Invoice deleted.', 'success')
    return redirect(url_for('ar.invoices'))


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
    item_list = invoice.items.order_by(InvoiceItem.id.asc()).all()
    payment_list = invoice.payments.order_by(Payment.date.desc()).all()

    revenue_total = 0.0
    cost_total = 0.0
    for item in item_list:
        qty = float(item.quantity or 0)
        revenue_total += float(item.amount or 0)
        if item.product and item.product.cost is not None:
            cost_total += float(item.product.cost or 0) * qty

    gross_profit = None
    margin_pct = None
    if cost_total > 0:
        gross_profit = revenue_total - cost_total
        if revenue_total > 0:
            margin_pct = (gross_profit / revenue_total) * 100

    delete_form = DeleteForm()
    return render_template(
        'ar/view_invoice.html',
        title=f'Invoice {invoice.number}',
        invoice=invoice,
        items=item_list,
        payments=payment_list,
        delete_form=delete_form,
        gross_profit=gross_profit,
        margin_pct=margin_pct,
    )


@bp.route('/invoice/<int:id>/pdf')
@login_required
def invoice_pdf(id):
    invoice = Invoice.query.get_or_404(id)
    items = invoice.items.order_by(InvoiceItem.id.asc()).all()
    pdf_data = _build_invoice_pdf(invoice, items)
    return send_file(
        BytesIO(pdf_data),
        mimetype='application/pdf',
        as_attachment=False,
        download_name=f"Invoice-{invoice.number}.pdf",
    )


@bp.route('/invoice/<int:id>/email', methods=['GET', 'POST'])
@login_required
def email_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    items = invoice.items.order_by(InvoiceItem.id.asc()).all()
    form = EmailInvoiceForm()

    if request.method == 'GET':
        if invoice.customer and invoice.customer.email:
            form.to_email.data = invoice.customer.email

    if form.validate_on_submit():
        subject = f"Invoice {invoice.number}"
        pdf_data = _build_invoice_pdf(invoice, items)
        sender = current_app.config.get('MAIL_DEFAULT_SENDER') or current_app.config['ADMINS'][0]
        recipients = [form.to_email.data]
        text_body = render_template('email/invoice.txt', invoice=invoice, message=form.message.data)
        html_body = render_template('email/invoice.html', invoice=invoice, message=form.message.data)

        try:
            send_email_with_attachments_sync(
                subject=subject,
                sender=sender,
                recipients=recipients,
                text_body=text_body,
                html_body=html_body,
                attachments=[(f"Invoice-{invoice.number}.pdf", 'application/pdf', pdf_data)],
            )
        except Exception as e:
            current_app.logger.exception('Failed to send invoice email')
            msg = str(e).strip() or 'Unknown error'
            flash(f'Failed to send email: {msg}', 'danger')
            return render_template('ar/email_invoice.html', title=f'Email Invoice {invoice.number}', form=form, invoice=invoice)

        flash('Invoice emailed.', 'success')
        return redirect(url_for('ar.view_invoice', id=invoice.id))

    return render_template('ar/email_invoice.html', title=f'Email Invoice {invoice.number}', form=form, invoice=invoice)
