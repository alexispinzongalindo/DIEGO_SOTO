from datetime import date
from decimal import Decimal
import os
import uuid
from pathlib import Path

from flask import render_template, redirect, url_for, flash, request, current_app, send_from_directory
from flask_login import login_required

from fpdf import FPDF

from app import db
from app.accounts_payable import bp
from app.accounts_payable.forms import VendorForm, BillForm, VendorPaymentForm, DeleteForm
from app.models import Vendor, Bill, VendorPayment, BillItem


def _digits_only(value: str) -> str:
    raw = (value or '').strip()
    digits = ''.join([c for c in raw if c.isdigit()])
    return digits


def _ensure_checks_folder() -> str:
    folder = os.path.join(current_app.static_folder, 'uploads', 'checks')
    Path(folder).mkdir(parents=True, exist_ok=True)
    return folder


def _money_to_words(amount: Decimal) -> str:
    # Demo-only: keep simple for now.
    try:
        n = Decimal(str(amount or 0)).quantize(Decimal('0.01'))
    except Exception:
        n = Decimal('0.00')
    return f"{n:,.2f} DOLLARS"


def _generate_dummy_voucher_check_pdf(*, vendor: Vendor, check_number: str, check_date: date, memo: str, applied_rows):
    pdf = FPDF(orientation='P', unit='mm', format='Letter')
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    pdf.set_font('Helvetica', size=12)

    # Header area (dummy)
    pdf.set_xy(10, 10)
    pdf.set_font('Helvetica', style='B', size=14)
    pdf.cell(0, 6, 'DUMMY CHECK (DEMO ONLY)', ln=1)
    pdf.set_font('Helvetica', size=10)
    pdf.cell(0, 5, 'Not valid for deposit. No bank/MICR information printed.', ln=1)

    # Check box layout (approximate; intended for demo printouts)
    y0 = 28
    pdf.set_draw_color(0, 0, 0)
    pdf.rect(10, y0, 195, 55)

    pdf.set_font('Helvetica', size=11)
    pdf.set_xy(12, y0 + 4)
    pdf.cell(25, 6, 'DATE:')
    pdf.set_xy(35, y0 + 4)
    pdf.cell(40, 6, check_date.strftime('%Y-%m-%d') if check_date else '')

    pdf.set_xy(140, y0 + 4)
    pdf.cell(30, 6, 'CHECK #')
    pdf.set_xy(165, y0 + 4)
    pdf.cell(35, 6, (check_number or '').strip())

    pdf.set_xy(12, y0 + 16)
    pdf.cell(50, 6, 'PAY TO THE ORDER OF:')
    pdf.set_xy(58, y0 + 16)
    pdf.set_font('Helvetica', style='B', size=12)
    pdf.cell(120, 6, (vendor.name or '').strip())
    pdf.set_font('Helvetica', size=11)

    total = sum((Decimal(str(r.get('amount') or 0)) for r in applied_rows), Decimal('0.00'))
    pdf.set_xy(140, y0 + 16)
    pdf.cell(20, 6, '$')
    pdf.set_xy(150, y0 + 16)
    pdf.set_font('Helvetica', style='B', size=12)
    pdf.cell(50, 6, f"{total:,.2f}")
    pdf.set_font('Helvetica', size=11)

    pdf.set_xy(12, y0 + 28)
    pdf.cell(25, 6, 'AMOUNT:')
    pdf.set_xy(35, y0 + 28)
    pdf.cell(160, 6, _money_to_words(total))

    if memo:
        pdf.set_xy(12, y0 + 40)
        pdf.cell(25, 6, 'MEMO:')
        pdf.set_xy(35, y0 + 40)
        pdf.cell(160, 6, memo)

    # Stub section
    y1 = 90
    pdf.set_font('Helvetica', style='B', size=12)
    pdf.set_xy(10, y1)
    pdf.cell(0, 6, 'VOUCHER STUB (DEMO)', ln=1)

    pdf.set_font('Helvetica', size=10)
    pdf.set_xy(10, y1 + 8)
    pdf.cell(0, 5, f"Vendor: {(vendor.name or '').strip()}    Check #: {(check_number or '').strip()}    Date: {check_date.strftime('%Y-%m-%d') if check_date else ''}", ln=1)

    # Table header
    ytbl = y1 + 18
    pdf.set_font('Helvetica', style='B', size=10)
    pdf.set_xy(10, ytbl)
    pdf.cell(45, 6, 'Bill #', border=1)
    pdf.cell(35, 6, 'Bill Date', border=1)
    pdf.cell(60, 6, 'Notes', border=1)
    pdf.cell(35, 6, 'Paid', border=1, ln=1, align='R')

    pdf.set_font('Helvetica', size=10)
    for row in applied_rows[:14]:
        bill_number = (row.get('bill_number') or '').strip()
        bill_date = row.get('bill_date')
        bill_date_str = bill_date.strftime('%Y-%m-%d') if bill_date else ''
        notes = (row.get('notes') or '').strip()
        amt = Decimal(str(row.get('amount') or 0)).quantize(Decimal('0.01'))

        pdf.set_x(10)
        pdf.cell(45, 6, bill_number, border=1)
        pdf.cell(35, 6, bill_date_str, border=1)
        pdf.cell(60, 6, notes[:28], border=1)
        pdf.cell(35, 6, f"{amt:,.2f}", border=1, ln=1, align='R')

    pdf.set_font('Helvetica', style='B', size=11)
    pdf.set_x(10)
    pdf.cell(140, 7, 'TOTAL', border=1)
    pdf.cell(35, 7, f"{total:,.2f}", border=1, ln=1, align='R')

    folder = _ensure_checks_folder()
    filename = f"check_{uuid.uuid4().hex}.pdf"
    abs_path = os.path.join(folder, filename)
    pdf.output(abs_path)
    return filename


def _update_bill_status(bill: Bill) -> None:
    if not bill:
        return
    try:
        if bill.balance <= 0.01:
            bill.status = 'paid'
        elif bill.paid_amount > 0:
            bill.status = 'partial'
        elif bill.is_overdue:
            bill.status = 'overdue'
        else:
            bill.status = 'open'
    except Exception:
        bill.status = bill.status or 'open'


@bp.route('/bills')
@login_required
def bills():
    bill_list = Bill.query.order_by(Bill.date.desc()).all()
    delete_form = DeleteForm()
    return render_template('ap/bills.html', title='Bills', bills=bill_list, delete_form=delete_form)


@bp.route('/vendors')
@login_required
def vendors():
    vendor_list = Vendor.query.order_by(Vendor.name.asc()).all()
    return render_template('ap/vendors.html', title='Vendors', vendors=vendor_list)


@bp.route('/pay-bills', methods=['GET', 'POST'])
@login_required
def pay_bills():
    vendors = Vendor.query.order_by(Vendor.name.asc()).all()
    if not vendors:
        flash('Create a vendor before paying bills.', 'warning')
        return redirect(url_for('ap.create_vendor'))

    vendor_id = request.args.get('vendor_id', type=int) or request.form.get('vendor_id', type=int)
    vendor = Vendor.query.get(vendor_id) if vendor_id else None

    bill_list = []
    if vendor:
        bill_list = (
            Bill.query
            .filter(Bill.vendor_id == vendor.id)
            .order_by(Bill.date.desc())
            .all()
        )
        bill_list = [b for b in bill_list if (b.status != 'paid' and (b.balance or 0) > 0.01)]

    if request.method == 'POST':
        if not vendor:
            flash('Select a vendor.', 'danger')
            return redirect(url_for('ap.pay_bills'))

        check_number = (request.form.get('check_number') or '').strip()
        payment_date = request.form.get('date')
        memo = (request.form.get('memo') or '').strip()

        try:
            pay_date = date.fromisoformat(payment_date) if payment_date else date.today()
        except Exception:
            pay_date = date.today()

        applied_rows = []
        payments_to_create = []
        for b in bill_list:
            if request.form.get(f'select_bill_{b.id}') != 'on':
                continue
            raw_amt = (request.form.get(f'amount_{b.id}') or '').strip()
            if not raw_amt:
                continue
            try:
                amt = Decimal(raw_amt)
            except Exception:
                continue
            if amt <= 0:
                continue
            if amt > Decimal(str(b.balance or 0)) + Decimal('0.01'):
                flash(f"Payment for bill {b.number} exceeds remaining balance.", 'danger')
                return redirect(url_for('ap.pay_bills', vendor_id=vendor.id))

            payments_to_create.append(
                VendorPayment(
                    date=pay_date,
                    vendor_id=vendor.id,
                    bill_id=b.id,
                    amount=amt,
                    payment_method='Check',
                    reference=check_number,
                    notes=memo,
                )
            )
            applied_rows.append({
                'bill_number': b.number,
                'bill_date': b.date,
                'notes': (b.notes or ''),
                'amount': amt,
            })

        if not payments_to_create:
            flash('Select at least one bill and enter an amount to pay.', 'warning')
            return redirect(url_for('ap.pay_bills', vendor_id=vendor.id))

        pdf_filename = _generate_dummy_voucher_check_pdf(
            vendor=vendor,
            check_number=check_number,
            check_date=pay_date,
            memo=memo,
            applied_rows=applied_rows,
        )

        for p in payments_to_create:
            p.check_pdf_filename = pdf_filename
            db.session.add(p)
        db.session.commit()

        for p in payments_to_create:
            bill = Bill.query.get(p.bill_id)
            if bill:
                _update_bill_status(bill)
        db.session.commit()

        flash('Check created (demo) and payments recorded.', 'success')
        return redirect(url_for('ap.view_check_pdf', filename=pdf_filename))

    return render_template(
        'ap/pay_bills.html',
        title='Pay Bills',
        vendors=vendors,
        vendor=vendor,
        bills=bill_list,
        today=date.today(),
    )


@bp.route('/checks/<path:filename>')
@login_required
def view_check_pdf(filename):
    folder = _ensure_checks_folder()
    return send_from_directory(folder, filename, mimetype='application/pdf')


@bp.route('/vendors/create', methods=['GET', 'POST'])
@login_required
def create_vendor():
    form = VendorForm()
    if form.validate_on_submit():
        vendor = Vendor(
            name=form.name.data,
            address=form.address.data,
            phone=form.phone.data,
            email=form.email.data,
            tax_id=form.tax_id.data,
            account_number=form.account_number.data,
        )
        db.session.add(vendor)
        db.session.commit()
        flash('Vendor created.', 'success')
        return redirect(url_for('ap.vendors'))
    return render_template('ap/create_vendor.html', title='Create Vendor', form=form)


@bp.route('/vendors/<int:id>')
@login_required
def view_vendor(id):
    vendor = Vendor.query.get_or_404(id)
    bill_list = vendor.bills.order_by(Bill.date.desc()).all()
    payment_list = vendor.payments.order_by(VendorPayment.date.desc()).all()
    return render_template(
        'ap/view_vendor.html',
        title=f'Vendor {vendor.name}',
        vendor=vendor,
        bills=bill_list,
        payments=payment_list,
    )


@bp.route('/vendors/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_vendor(id):
    vendor = Vendor.query.get_or_404(id)
    form = VendorForm(obj=vendor)
    if form.validate_on_submit():
        vendor.name = form.name.data
        vendor.address = form.address.data
        vendor.phone = form.phone.data
        vendor.email = form.email.data
        vendor.tax_id = form.tax_id.data
        vendor.account_number = form.account_number.data
        db.session.commit()
        flash('Vendor updated.', 'success')
        return redirect(url_for('ap.view_vendor', id=vendor.id))
    return render_template('ap/edit_vendor.html', title=f'Edit Vendor {vendor.name}', form=form, vendor=vendor)


@bp.route('/payments')
@login_required
def payments():
    payment_list = VendorPayment.query.order_by(VendorPayment.date.desc()).all()
    return render_template('ap/payments.html', title='Payments', payments=payment_list)


@bp.route('/bill/create', methods=['GET', 'POST'])
@login_required
def create_bill():
    vendors = Vendor.query.order_by(Vendor.name.asc()).all()
    if not vendors:
        flash('Create a vendor before creating a bill.', 'warning')
        return redirect(url_for('ap.create_vendor'))

    form = BillForm()
    form.vendor_id.choices = [(v.id, v.name) for v in vendors]

    if request.method == 'GET':
        form.date.data = date.today()
        if not form.vendor_id.data:
            form.vendor_id.data = vendors[0].id

    if form.validate_on_submit():
        bill_number = _digits_only(form.number.data)
        if not bill_number:
            flash('Bill number must contain only numbers.', 'danger')
            return render_template('ap/create_bill.html', title='Create Bill', form=form)
        item_rows = []
        subtotal = 0.0
        for item_form in form.items:
            description = (item_form.form.description.data or '').strip()
            qty = item_form.form.quantity.data
            unit_price = item_form.form.unit_price.data

            is_blank = (not description) and (qty is None) and (unit_price is None)
            if is_blank:
                continue

            if not description:
                flash('Each bill item must include a description.', 'danger')
                return render_template('ap/create_bill.html', title='Create Bill', form=form)

            if qty is None:
                flash('Each bill item must include a quantity.', 'danger')
                return render_template('ap/create_bill.html', title='Create Bill', form=form)

            if unit_price is None:
                flash('Each bill item must include a unit price.', 'danger')
                return render_template('ap/create_bill.html', title='Create Bill', form=form)

            amount = float(qty) * float(unit_price)
            subtotal += amount
            item_rows.append({
                'description': description,
                'quantity': qty,
                'unit_price': unit_price,
                'amount': amount,
            })

        if not item_rows:
            flash('Add at least one bill item.', 'danger')
            return render_template('ap/create_bill.html', title='Create Bill', form=form)

        tax = float(form.tax.data or 0)
        total = subtotal + tax

        bill = Bill(
            number=bill_number,
            date=form.date.data,
            due_date=form.due_date.data,
            vendor_id=form.vendor_id.data,
            subtotal=subtotal,
            tax=tax,
            total=total,
            status='open',
            terms=form.terms.data,
            notes=form.notes.data,
        )
        db.session.add(bill)

        for row in item_rows:
            bill_item = BillItem(
                bill=bill,
                description=row['description'],
                quantity=row['quantity'],
                unit_price=row['unit_price'],
                amount=row['amount'],
            )
            db.session.add(bill_item)

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Unable to create bill. Make sure the bill number is unique.', 'danger')
            return render_template('ap/create_bill.html', title='Create Bill', form=form)

        flash('Bill created.', 'success')
        return redirect(url_for('ap.view_bill', id=bill.id))

    return render_template('ap/create_bill.html', title='Create Bill', form=form)


@bp.route('/payment/record', methods=['GET', 'POST'])
@login_required
def record_payment():
    vendors = Vendor.query.order_by(Vendor.name.asc()).all()
    if not vendors:
        flash('Create a vendor before recording a payment.', 'warning')
        return redirect(url_for('ap.create_vendor'))

    form = VendorPaymentForm()
    form.vendor_id.choices = [(v.id, v.name) for v in vendors]

    preselect_bill_id = request.args.get('bill_id', type=int)
    selected_vendor_id = request.args.get('vendor_id', type=int)
    if preselect_bill_id:
        bill = Bill.query.get(preselect_bill_id)
        if bill:
            selected_vendor_id = bill.vendor_id

    if request.method == 'GET':
        form.date.data = date.today()
        if selected_vendor_id:
            form.vendor_id.data = selected_vendor_id
        if not form.vendor_id.data:
            form.vendor_id.data = vendors[0].id
        if preselect_bill_id:
            form.bill_id.data = preselect_bill_id

    bill_list = Bill.query.order_by(Bill.date.desc()).all()
    form.bill_id.choices = [(0, '-- None --')] + [
        (b.id, f"{b.vendor.name if b.vendor else ''} - {b.number}") for b in bill_list
    ]

    if form.validate_on_submit():
        bill_id = form.bill_id.data or 0
        if bill_id == 0:
            bill_id = None

        if bill_id:
            bill = Bill.query.get(bill_id)
            if not bill:
                flash('Selected bill was not found.', 'danger')
                return render_template('ap/record_payment.html', title='Pay Bill', form=form)
            form.vendor_id.data = bill.vendor_id

        payment = VendorPayment(
            date=form.date.data,
            vendor_id=form.vendor_id.data,
            bill_id=bill_id,
            amount=form.amount.data,
            payment_method=form.payment_method.data,
            reference=form.reference.data,
            notes=form.notes.data,
        )
        db.session.add(payment)
        db.session.commit()

        if bill_id:
            bill = Bill.query.get(bill_id)
            if bill:
                if bill.balance <= 0.01:
                    bill.status = 'paid'
                elif bill.paid_amount > 0:
                    bill.status = 'partial'
                elif bill.is_overdue:
                    bill.status = 'overdue'
                else:
                    bill.status = 'open'
                db.session.commit()

        flash('Payment recorded.', 'success')
        if bill_id:
            return redirect(url_for('ap.view_bill', id=bill_id))
        return redirect(url_for('ap.payments'))

    return render_template('ap/record_payment.html', title='Pay Bill', form=form)


@bp.route('/bill/<int:id>')
@login_required
def view_bill(id):
    bill = Bill.query.get_or_404(id)
    if bill.status != 'paid' and bill.is_overdue and bill.balance > 0:
        bill.status = 'overdue'
        db.session.commit()
    item_list = bill.items.order_by(BillItem.id.asc()).all()
    payment_list = bill.payments.order_by(VendorPayment.date.desc()).all()
    delete_form = DeleteForm()
    return render_template(
        'ap/view_bill.html',
        title=f'Bill {bill.number}',
        bill=bill,
        items=item_list,
        payments=payment_list,
        delete_form=delete_form,
    )


@bp.route('/bill/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_bill(id):
    bill = Bill.query.get_or_404(id)

    vendors = Vendor.query.order_by(Vendor.name.asc()).all()
    if not vendors:
        flash('Create a vendor before editing a bill.', 'warning')
        return redirect(url_for('ap.create_vendor'))

    form = BillForm(obj=bill)
    form.submit.label.text = 'Save Bill'
    form.vendor_id.choices = [(v.id, v.name) for v in vendors]

    if request.method == 'GET':
        form.vendor_id.data = bill.vendor_id
        existing_items = bill.items.order_by(BillItem.id.asc()).all()
        for idx, bill_item in enumerate(existing_items[: len(form.items)]):
            form.items[idx].form.description.data = bill_item.description
            form.items[idx].form.quantity.data = bill_item.quantity
            form.items[idx].form.unit_price.data = bill_item.unit_price

    if form.validate_on_submit():
        bill_number = _digits_only(form.number.data)
        if not bill_number:
            flash('Bill number must contain only numbers.', 'danger')
            return render_template('ap/edit_bill.html', title=f'Edit Bill {bill.number}', form=form, bill=bill)
        item_rows = []
        subtotal = 0.0
        for item_form in form.items:
            description = (item_form.form.description.data or '').strip()
            qty = item_form.form.quantity.data
            unit_price = item_form.form.unit_price.data

            is_blank = (not description) and (qty is None) and (unit_price is None)
            if is_blank:
                continue

            if not description:
                flash('Each bill item must include a description.', 'danger')
                return render_template('ap/edit_bill.html', title=f'Edit Bill {bill.number}', form=form, bill=bill)

            if qty is None:
                flash('Each bill item must include a quantity.', 'danger')
                return render_template('ap/edit_bill.html', title=f'Edit Bill {bill.number}', form=form, bill=bill)

            if unit_price is None:
                flash('Each bill item must include a unit price.', 'danger')
                return render_template('ap/edit_bill.html', title=f'Edit Bill {bill.number}', form=form, bill=bill)

            amount = float(qty) * float(unit_price)
            subtotal += amount
            item_rows.append({
                'description': description,
                'quantity': qty,
                'unit_price': unit_price,
                'amount': amount,
            })

        if not item_rows:
            flash('Add at least one bill item.', 'danger')
            return render_template('ap/edit_bill.html', title=f'Edit Bill {bill.number}', form=form, bill=bill)

        tax = float(form.tax.data or 0)
        total = subtotal + tax

        bill.number = bill_number
        bill.date = form.date.data
        bill.due_date = form.due_date.data
        bill.vendor_id = form.vendor_id.data
        bill.subtotal = subtotal
        bill.tax = tax
        bill.total = total
        bill.terms = form.terms.data
        bill.notes = form.notes.data

        existing_items = bill.items.all()
        for bill_item in existing_items:
            db.session.delete(bill_item)
        db.session.flush()

        for row in item_rows:
            bill_item = BillItem(
                bill=bill,
                description=row['description'],
                quantity=row['quantity'],
                unit_price=row['unit_price'],
                amount=row['amount'],
            )
            db.session.add(bill_item)

        if bill.balance <= 0.01:
            bill.status = 'paid'
        elif bill.paid_amount > 0:
            bill.status = 'partial'
        elif bill.is_overdue and bill.balance > 0:
            bill.status = 'overdue'
        else:
            bill.status = 'open'

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Unable to update bill. Make sure the bill number is unique.', 'danger')
            return render_template('ap/edit_bill.html', title=f'Edit Bill {bill.number}', form=form, bill=bill)

        flash('Bill updated.', 'success')
        return redirect(url_for('ap.view_bill', id=bill.id))

    return render_template('ap/edit_bill.html', title=f'Edit Bill {bill.number}', form=form, bill=bill)


@bp.route('/bill/<int:id>/delete', methods=['POST'])
@login_required
def delete_bill(id):
    bill = Bill.query.get_or_404(id)
    form = DeleteForm()
    if not form.validate_on_submit():
        flash('Unable to delete bill.', 'danger')
        return redirect(url_for('ap.view_bill', id=bill.id))

    if bill.payments.count() > 0:
        flash('Cannot delete a bill that has payments recorded.', 'warning')
        return redirect(url_for('ap.view_bill', id=bill.id))

    items = bill.items.all()
    for bill_item in items:
        db.session.delete(bill_item)
    db.session.delete(bill)
    db.session.commit()
    flash('Bill deleted.', 'success')
    return redirect(url_for('ap.bills'))
