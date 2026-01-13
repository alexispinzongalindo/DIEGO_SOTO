from datetime import date, timedelta
from io import BytesIO
import os
import re

from flask import render_template, redirect, url_for, flash, request, send_file, current_app
from flask_login import login_required
from fpdf import FPDF
from sqlalchemy import inspect

from app import db
from app.accounts_receivable import bp
from app.accounts_receivable.forms import CustomerForm, InvoiceForm, QuoteForm, PaymentForm, EmailInvoiceForm, ItemForm, DeleteForm
from app.auth.email import send_email_with_attachments_sync
from app.models import Customer, Invoice, Quote, Payment, InvoiceItem, QuoteItem, Product, AppSetting


def _digits_only(value: str) -> str:
    raw = (value or '').strip()
    digits = ''.join([c for c in raw if c.isdigit()])
    return digits


def _compute_due_date(invoice_date, terms: str):
    if not invoice_date:
        return None
    t = (terms or '').strip().lower()
    if not t:
        return None
    m = re.search(r'(\d{1,3})', t)
    if not m:
        return None
    try:
        days = int(m.group(1))
    except Exception:
        return None
    if days < 0 or days > 3650:
        return None
    return invoice_date + timedelta(days=days)


def _company_header_settings() -> dict:
    try:
        if not inspect(db.engine).has_table('app_setting'):
            return {}
        keys = ['company_name', 'company_address', 'company_phone', 'company_fax', 'company_email', 'company_logo_path']
        rows = AppSetting.query.filter(AppSetting.key.in_(keys)).all()
        vals = {r.key: (r.value or '').strip() for r in rows}
        return {
            'name': vals.get('company_name', ''),
            'address': vals.get('company_address', ''),
            'phone': vals.get('company_phone', ''),
            'fax': vals.get('company_fax', ''),
            'email': vals.get('company_email', ''),
            'logo_path': vals.get('company_logo_path', ''),
        }
    except Exception:
        db.session.rollback()
        return {}


def _resolve_logo_abs_path(logo_path: str) -> str:
    raw = (logo_path or '').strip()
    candidates: list[str] = []

    if raw:
        candidates.append(raw)
        candidates.append(raw.lstrip('/'))
    candidates.append('static/img/logo.png')
    candidates.append('static/img/logo.jpg')
    candidates.append('static/img/logo.jpeg')
    candidates.append('static/logo.png')
    candidates.append('static/logo.jpg')
    candidates.append('static/logo.jpeg')

    for c in candidates:
        if not c:
            continue
        if os.path.isabs(c):
            if os.path.exists(c):
                return c
            continue
        abs_path = os.path.join(current_app.root_path, c)
        if os.path.exists(abs_path):
            return abs_path
    return ''


def _render_company_header_pdf(pdf: FPDF) -> None:
    header = _company_header_settings()
    logo_path = (header.get('logo_path') or '').strip()
    name = (header.get('name') or '').strip()
    address = (header.get('address') or '').strip()
    phone = (header.get('phone') or '').strip()
    fax = (header.get('fax') or '').strip()
    email = (header.get('email') or '').strip()

    start_y = 10
    abs_logo = _resolve_logo_abs_path(logo_path)
    if abs_logo:
        try:
            pdf.image(abs_logo, x=10, y=start_y, w=28)
        except Exception:
            pass

    x_text = 42
    y = start_y

    if name:
        pdf.set_xy(x_text, y)
        pdf.set_font('Helvetica', 'B', 14)
        pdf.cell(0, 6, name, ln=True)
        y = pdf.get_y()

    pdf.set_font('Helvetica', '', 10)

    if address:
        for line in [ln.strip() for ln in address.splitlines() if ln.strip()]:
            pdf.set_x(x_text)
            pdf.cell(0, 5, line, ln=True)
        y = pdf.get_y()

    if phone or fax or email:
        parts = []
        if phone:
            parts.append(f"TELS. {phone}")
        if fax:
            parts.append(f"FAX {fax}")
        if email:
            parts.append(email)
        contact = ' / '.join([p for p in parts if p])
        pdf.set_x(x_text)
        pdf.cell(0, 5, contact, ln=True)
        y = pdf.get_y()

    if y < 30:
        y = 30
    pdf.ln(2)


def _pdf_cell_text(value) -> str:
    return (value or '').strip()


def _pdf_money(value) -> str:
    try:
        return f"${float(value or 0):,.2f}"
    except Exception:
        return "$0.00"


def _pdf_lines_for_width(pdf: FPDF, text: str, width: float) -> list[str]:
    text = (text or '').strip()
    if not text:
        return ['']
    try:
        # fpdf2
        lines = pdf.multi_cell(width, 4.5, text, split_only=True)
        return lines or ['']
    except Exception:
        return [text]


def _pdf_table_row(pdf: FPDF, cols: list[dict], y: float, row_min_h: float = 6.0) -> float:
    # cols: [{x,w,text,align}]
    heights = []
    for c in cols:
        lines = _pdf_lines_for_width(pdf, c.get('text', ''), c['w'])
        heights.append(max(row_min_h, len(lines) * 4.5))
    h = max(heights) if heights else row_min_h
    for c in cols:
        x = c['x']
        w = c['w']
        text = c.get('text', '')
        align = c.get('align', 'L')
        pdf.set_xy(x, y)
        pdf.multi_cell(w, 4.5, text, border=1, align=align)
        # restore y to top of row for next cell
        pdf.set_y(y)
    return y + h


def _build_quote_pdf(quote, items):
    pdf = FPDF(format='Letter', unit='mm')
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.add_page()

    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)

    # Header
    header = _company_header_settings()
    logo_path = _pdf_cell_text(header.get('logo_path'))
    name = _pdf_cell_text(header.get('name'))
    address = _pdf_cell_text(header.get('address'))
    phone = _pdf_cell_text(header.get('phone'))
    fax = _pdf_cell_text(header.get('fax'))
    email = _pdf_cell_text(header.get('email'))

    pdf.rect(10, 10, 190, 30)
    pdf.rect(10, 10, 70, 30)
    pdf.rect(80, 10, 120, 30)

    abs_logo = _resolve_logo_abs_path(logo_path)
    if abs_logo:
        try:
            pdf.image(abs_logo, x=12, y=12, w=30)
        except Exception:
            pass

    pdf.set_xy(12, 30)
    pdf.set_font('Helvetica', '', 8)
    if name:
        pdf.cell(66, 4, name, ln=False)

    pdf.set_xy(82, 12)
    pdf.set_font('Helvetica', 'B', 9)
    if address:
        addr_lines = [ln.strip() for ln in address.splitlines() if ln.strip()]
    else:
        addr_lines = []
    top_right_lines = addr_lines[:4]
    for ln in top_right_lines:
        pdf.cell(116, 4, ln, ln=True, align='R')
        pdf.set_x(82)
    pdf.set_font('Helvetica', '', 8)
    contact_parts = []
    if phone:
        contact_parts.append(f"TELS. {phone}")
    if fax:
        contact_parts.append(f"FAX {fax}")
    if email:
        contact_parts.append(email)
    contact = ' / '.join([p for p in contact_parts if p])
    if contact:
        pdf.set_x(82)
        pdf.cell(116, 4, contact, ln=True, align='R')

    # Bill to + Quote box
    pdf.rect(10, 42, 110, 26)
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_xy(12, 44)
    pdf.cell(0, 4, 'BILL TO')
    pdf.set_font('Helvetica', '', 8)
    bill_name = _pdf_cell_text(getattr(quote.customer, 'name', '') if quote.customer else '')
    bill_addr = _pdf_cell_text(getattr(quote.customer, 'address', '') if quote.customer else '')
    pdf.set_xy(12, 49)
    pdf.multi_cell(106, 4, '\n'.join([ln for ln in [bill_name] + bill_addr.splitlines() if ln.strip()]))

    pdf.rect(120, 42, 80, 26)
    pdf.set_font('Helvetica', 'B', 12)
    pdf.set_xy(122, 44)
    pdf.cell(76, 6, 'QUOTE', ln=True, align='R')
    pdf.set_font('Helvetica', 'B', 7)
    pdf.set_xy(122, 52)
    pdf.cell(20, 6, 'DATE', border=1, align='C')
    pdf.cell(28, 6, 'QUOTE NO.', border=1, align='C')
    pdf.cell(28, 6, 'VALID UNTIL', border=1, align='C')
    pdf.set_font('Helvetica', '', 7)
    pdf.set_xy(122, 58)
    pdf.cell(20, 6, quote.date.strftime('%m/%d/%Y') if quote.date else '', border=1, align='C')
    pdf.cell(28, 6, _pdf_cell_text(quote.number), border=1, align='C')
    pdf.cell(28, 6, quote.valid_until.strftime('%m/%d/%Y') if quote.valid_until else '', border=1, align='C')

    # Field strip
    y_strip = 70
    pdf.set_font('Helvetica', 'B', 7)
    pdf.rect(10, y_strip, 190, 10)
    col_defs = [
        ('PROJECT', 55, _pdf_cell_text(getattr(quote, 'project', ''))),
        ('TERMS', 28, _pdf_cell_text(getattr(quote, 'terms', ''))),
        ('REP', 20, _pdf_cell_text(getattr(quote, 'rep', ''))),
        ('CUST. TEL.', 43, _pdf_cell_text(getattr(quote, 'customer_tel', ''))),
        ('CUST. FAX', 44, _pdf_cell_text(getattr(quote, 'customer_fax', ''))),
    ]
    x = 10
    for label, w, _ in col_defs:
        pdf.rect(x, y_strip, w, 5)
        pdf.set_xy(x, y_strip + 1)
        pdf.cell(w, 3, label, align='C')
        x += w
    pdf.set_font('Helvetica', '', 7)
    x = 10
    for _, w, value in col_defs:
        pdf.rect(x, y_strip + 5, w, 5)
        pdf.set_xy(x + 1, y_strip + 6)
        pdf.cell(w - 2, 3, value, align='L')
        x += w

    # Table header
    y_table = 82
    pdf.set_font('Helvetica', 'B', 7)
    pdf.rect(10, y_table, 190, 7)
    pdf.rect(10, y_table, 20, 7)
    pdf.rect(30, y_table, 20, 7)
    pdf.rect(50, y_table, 120, 7)
    pdf.rect(170, y_table, 30, 7)
    pdf.set_xy(10, y_table + 2)
    pdf.cell(20, 3, 'QTY', align='C')
    pdf.set_xy(30, y_table + 2)
    pdf.cell(20, 3, 'UNIT', align='C')
    pdf.set_xy(50, y_table + 2)
    pdf.cell(120, 3, 'DESCRIPTION', align='C')
    pdf.set_xy(170, y_table + 2)
    pdf.cell(30, 3, 'TOTAL', align='C')

    # Items
    pdf.set_font('Helvetica', '', 7)
    y = y_table + 7
    for item in items:
        desc = item.description or (item.product.description if item.product else '')
        qty = f"{float(item.quantity or 0):g}" if item.quantity is not None else ''
        unit = (getattr(item, 'unit', None) or (item.product.unit if item.product else '') or '').strip()
        amount = _pdf_money(item.amount)
        y = _pdf_table_row(
            pdf,
            cols=[
                {'x': 10, 'w': 20, 'text': qty, 'align': 'C'},
                {'x': 30, 'w': 20, 'text': unit, 'align': 'C'},
                {'x': 50, 'w': 120, 'text': _pdf_cell_text(desc), 'align': 'L'},
                {'x': 170, 'w': 30, 'text': amount, 'align': 'R'},
            ],
            y=y,
            row_min_h=6.0,
        )
        if y > 235:
            pdf.add_page()
            y = 20

    # Totals box
    box_h = 10
    pdf.set_font('Helvetica', 'B', 9)
    pdf.rect(140, 245, 60, box_h)
    pdf.set_xy(142, 247)
    pdf.cell(26, 6, 'TOTAL', align='L')
    pdf.cell(32, 6, _pdf_money(quote.total), align='R')

    # Signature line (matches sample position)
    pdf.set_font('Helvetica', '', 7)
    pdf.set_xy(10, 245)
    pdf.cell(90, 5, 'AUTHORIZED SIGNATURE', ln=True)
    pdf.line(10, 252, 110, 252)

    # Printed notes in blue (sample block)
    printed = (getattr(quote, 'printed_notes', None) or '').strip()
    if printed:
        pdf.set_text_color(0, 0, 160)
        pdf.set_font('Helvetica', '', 6)
        pdf.set_xy(10, 257)
        pdf.multi_cell(190, 3.2, printed)
        pdf.set_text_color(0, 0, 0)

    out = pdf.output(dest='S')
    if isinstance(out, str):
        out = out.encode('latin-1')
    return out


def _build_invoice_pdf(invoice, items):
    pdf = FPDF(format='Letter', unit='mm')
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.add_page()

    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)

    header = _company_header_settings()
    logo_path = _pdf_cell_text(header.get('logo_path'))
    name = _pdf_cell_text(header.get('name'))
    address = _pdf_cell_text(header.get('address'))
    phone = _pdf_cell_text(header.get('phone'))
    fax = _pdf_cell_text(header.get('fax'))
    email = _pdf_cell_text(header.get('email'))

    pdf.rect(10, 10, 190, 30)
    pdf.rect(10, 10, 70, 30)
    pdf.rect(80, 10, 120, 30)

    abs_logo = _resolve_logo_abs_path(logo_path)
    if abs_logo:
        try:
            pdf.image(abs_logo, x=12, y=12, w=30)
        except Exception:
            pass

    pdf.set_xy(12, 30)
    pdf.set_font('Helvetica', '', 8)
    if name:
        pdf.cell(66, 4, name, ln=False)

    pdf.set_xy(82, 12)
    pdf.set_font('Helvetica', 'B', 9)
    addr_lines = [ln.strip() for ln in address.splitlines() if ln.strip()] if address else []
    top_right_lines = addr_lines[:4]
    for ln in top_right_lines:
        pdf.cell(116, 4, ln, ln=True, align='R')
        pdf.set_x(82)
    pdf.set_font('Helvetica', '', 8)
    contact_parts = []
    if phone:
        contact_parts.append(f"TELS. {phone}")
    if fax:
        contact_parts.append(f"FAX {fax}")
    if email:
        contact_parts.append(email)
    contact = ' / '.join([p for p in contact_parts if p])
    if contact:
        pdf.set_x(82)
        pdf.cell(116, 4, contact, ln=True, align='R')

    # Bill to
    pdf.rect(10, 42, 110, 26)
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_xy(12, 44)
    pdf.cell(0, 4, 'BILL TO')
    pdf.set_font('Helvetica', '', 8)
    bill_name = _pdf_cell_text(invoice.bill_to_name) or _pdf_cell_text(getattr(invoice.customer, 'name', '') if invoice.customer else '')
    bill_addr = _pdf_cell_text(invoice.bill_to_address) or _pdf_cell_text(getattr(invoice.customer, 'address', '') if invoice.customer else '')
    pdf.set_xy(12, 49)
    pdf.multi_cell(106, 4, '\n'.join([ln for ln in [bill_name] + bill_addr.splitlines() if ln.strip()]))

    # Invoice box
    pdf.rect(120, 42, 80, 16)
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_xy(122, 44)
    pdf.cell(76, 6, 'Invoice', ln=True, align='R')
    pdf.set_font('Helvetica', 'B', 7)
    pdf.set_xy(122, 50)
    pdf.cell(26, 6, 'DATE', border=1, align='C')
    pdf.cell(54, 6, 'INVOICE NO.', border=1, align='C')
    pdf.set_font('Helvetica', '', 7)
    pdf.set_xy(122, 56)
    pdf.cell(26, 6, invoice.date.strftime('%m/%d/%Y') if invoice.date else '', border=1, align='C')
    pdf.cell(54, 6, _pdf_cell_text(invoice.number), border=1, align='C')

    # Customer fax/phone/alt phone block
    pdf.rect(120, 60, 80, 18)
    pdf.set_font('Helvetica', 'B', 7)
    pdf.set_xy(120, 60)
    pdf.cell(40, 6, 'Customer Fax', border=1, align='C')
    pdf.cell(40, 6, 'Customer Phone', border=1, align='C')
    pdf.set_xy(120, 66)
    pdf.set_font('Helvetica', '', 7)
    fax = _pdf_cell_text(getattr(invoice.customer, 'fax', '') if invoice.customer else '')
    phone_val = _pdf_cell_text(getattr(invoice.customer, 'phone', '') if invoice.customer else '')
    pdf.cell(40, 6, fax, border=1, align='C')
    pdf.cell(40, 6, phone_val, border=1, align='C')
    pdf.set_xy(120, 72)
    pdf.set_font('Helvetica', 'B', 7)
    pdf.cell(80, 6, 'Customer Alt. Phone', border=1, align='C')
    pdf.set_xy(120, 78)
    pdf.set_font('Helvetica', '', 7)
    alt_phone = _pdf_cell_text(getattr(invoice.customer, 'alt_phone', '') if invoice.customer else '')
    pdf.cell(80, 6, alt_phone, border=1, align='C')

    # Field strip row
    y_strip = 80
    pdf.rect(10, y_strip, 190, 10)
    pdf.set_font('Helvetica', 'B', 7)
    col_defs = [
        ('CUST. P.O.#', 34, _pdf_cell_text(getattr(invoice, 'customer_po', ''))),
        ('TERMS', 26, _pdf_cell_text(getattr(invoice, 'terms', ''))),
        ('REP', 18, _pdf_cell_text(getattr(invoice, 'rep', ''))),
        ('SHIP DATE', 26, invoice.ship_date.strftime('%m/%d/%Y') if invoice.ship_date else ''),
        ('SHIP VIA', 28, _pdf_cell_text(getattr(invoice, 'ship_via', ''))),
        ('FOB', 16, _pdf_cell_text(getattr(invoice, 'fob', ''))),
        ('PROJECT', 42, _pdf_cell_text(getattr(invoice, 'project', ''))),
    ]
    x = 10
    for label, w, _ in col_defs:
        pdf.rect(x, y_strip, w, 5)
        pdf.set_xy(x, y_strip + 1)
        pdf.cell(w, 3, label, align='C')
        x += w
    pdf.set_font('Helvetica', '', 7)
    x = 10
    for _, w, value in col_defs:
        pdf.rect(x, y_strip + 5, w, 5)
        pdf.set_xy(x + 1, y_strip + 6)
        pdf.cell(w - 2, 3, value, align='L')
        x += w

    # Table header
    y_table = 92
    pdf.set_font('Helvetica', 'B', 7)
    pdf.rect(10, y_table, 190, 7)
    pdf.rect(10, y_table, 20, 7)
    pdf.rect(30, y_table, 20, 7)
    pdf.rect(50, y_table, 120, 7)
    pdf.rect(170, y_table, 30, 7)
    pdf.set_xy(10, y_table + 2)
    pdf.cell(20, 3, 'QTY', align='C')
    pdf.set_xy(30, y_table + 2)
    pdf.cell(20, 3, 'UNIT', align='C')
    pdf.set_xy(50, y_table + 2)
    pdf.cell(120, 3, 'DESCRIPTION', align='C')
    pdf.set_xy(170, y_table + 2)
    pdf.cell(30, 3, 'AMOUNT', align='C')

    # Items
    pdf.set_font('Helvetica', '', 7)
    y = y_table + 7
    for item in items:
        desc = item.description or (item.product.description if item.product else '')
        qty = f"{float(item.quantity or 0):g}" if item.quantity is not None else ''
        unit = (getattr(item, 'unit', None) or (item.product.unit if item.product else '') or '').strip()
        amount = _pdf_money(item.amount)
        y = _pdf_table_row(
            pdf,
            cols=[
                {'x': 10, 'w': 20, 'text': qty, 'align': 'C'},
                {'x': 30, 'w': 20, 'text': unit, 'align': 'C'},
                {'x': 50, 'w': 120, 'text': _pdf_cell_text(desc), 'align': 'L'},
                {'x': 170, 'w': 30, 'text': amount, 'align': 'R'},
            ],
            y=y,
            row_min_h=6.0,
        )
        if y > 235:
            pdf.add_page()
            y = 20

    # Totals
    pdf.set_font('Helvetica', '', 8)
    pdf.set_xy(140, 245)
    pdf.cell(30, 5, 'Subtotal', align='R')
    pdf.cell(30, 5, _pdf_money(invoice.subtotal), ln=True, align='R')
    pdf.set_x(140)
    pdf.cell(30, 5, 'Tax', align='R')
    pdf.cell(30, 5, _pdf_money(invoice.tax), ln=True, align='R')
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_x(140)
    pdf.cell(30, 6, 'Total', align='R')
    pdf.cell(30, 6, _pdf_money(invoice.total), ln=True, align='R')

    # Side notes (prints separately; kept simple box)
    side_notes = (getattr(invoice, 'side_notes', None) or '').strip()
    if side_notes:
        pdf.set_font('Helvetica', '', 6)
        pdf.rect(10, 245, 120, 25)
        pdf.set_xy(12, 247)
        pdf.multi_cell(116, 3.2, side_notes)

    out = pdf.output(dest='S')
    if isinstance(out, str):
        out = out.encode('latin-1')
    return out


def _next_quote_number():
    last = Quote.query.order_by(Quote.id.desc()).first()
    if not last or not last.number:
        return '0001'
    try:
        digits = _digits_only(last.number)
        n = int(digits)
        return f"{n + 1:04d}"
    except Exception:
        return f"{(last.id + 1):04d}"


def _next_invoice_number():
    last = Invoice.query.order_by(Invoice.id.desc()).first()
    if not last or not last.number:
        return '0001'
    try:
        digits = _digits_only(last.number)
        n = int(digits)
        return f"{n + 1:04d}"
    except Exception:
        return f"{(last.id + 1):04d}"


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
    delete_form = DeleteForm()
    return render_template(
        'ar/view_customer.html',
        title=f'Customer {customer.name}',
        customer=customer,
        invoices=invoice_list,
        payments=payment_list,
        delete_form=delete_form,
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
        customer.fax = form.fax.data
        customer.alt_phone = form.alt_phone.data
        customer.email = form.email.data
        customer.tax_id = form.tax_id.data
        customer.credit_limit = form.credit_limit.data
        db.session.commit()
        flash('Customer updated.', 'success')
        return redirect(url_for('ar.view_customer', id=customer.id))

    return render_template('ar/edit_customer.html', title=f'Edit Customer {customer.name}', form=form, customer=customer)


@bp.route('/customers/<int:id>/delete', methods=['POST'])
@login_required
def delete_customer(id):
    customer = Customer.query.get_or_404(id)
    form = DeleteForm()
    if not form.validate_on_submit():
        flash('Unable to delete customer.', 'danger')
        return redirect(url_for('ar.view_customer', id=customer.id))

    if customer.invoices.count() > 0 or customer.quotes.count() > 0 or customer.payments.count() > 0 or customer.purchase_orders.count() > 0:
        flash('Cannot delete a customer with related transactions (invoices, quotes, payments, or purchase orders).', 'warning')
        return redirect(url_for('ar.view_customer', id=customer.id))

    db.session.delete(customer)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('Unable to delete customer.', 'danger')
        return redirect(url_for('ar.view_customer', id=customer.id))

    flash('Customer deleted.', 'success')
    return redirect(url_for('ar.customers'))


@bp.route('/customers/create', methods=['GET', 'POST'])
@login_required
def create_customer():
    form = CustomerForm()
    if form.validate_on_submit():
        customer = Customer(
            name=form.name.data,
            address=form.address.data,
            phone=form.phone.data,
            fax=form.fax.data,
            alt_phone=form.alt_phone.data,
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

    form = InvoiceForm()
    form.customer_id.choices = [(c.id, c.name) for c in customers]

    if request.method == 'GET':
        form.date.data = date.today()
        if not form.customer_id.data:
            form.customer_id.data = customers[0].id
        if not (form.number.data or '').strip():
            form.number.data = _next_invoice_number()
        if not (form.terms.data or '').strip():
            form.terms.data = 'Net 30'
        if not form.due_date.data:
            computed = _compute_due_date(form.date.data, form.terms.data)
            if computed:
                form.due_date.data = computed

        selected = Customer.query.get(form.customer_id.data)
        if selected:
            if not (form.bill_to_name.data or '').strip():
                form.bill_to_name.data = selected.name
            if not (form.bill_to_address.data or '').strip():
                form.bill_to_address.data = selected.address
            if not (form.ship_to_name.data or '').strip():
                form.ship_to_name.data = selected.name
            if not (form.ship_to_address.data or '').strip():
                form.ship_to_address.data = selected.address

    if form.validate_on_submit():
        invoice_number = _digits_only(form.number.data)
        if not invoice_number:
            flash('Invoice number must contain only numbers.', 'danger')
            return render_template('ar/create_invoice.html', title='Create Invoice', form=form)
        item_rows = []
        subtotal = 0.0
        for item_form in form.items:
            description = (item_form.form.description.data or '').strip()
            qty = item_form.form.quantity.data
            unit = (item_form.form.unit.data or '').strip() or None
            unit_price = item_form.form.unit_price.data

            is_blank = (not description) and (qty is None) and (unit_price is None)
            if is_blank:
                continue

            if not description:
                flash('Each invoice item must include a description.', 'danger')
                return render_template('ar/create_invoice.html', title='Create Invoice', form=form)

            if qty is None:
                flash('Each invoice item must include a quantity.', 'danger')
                return render_template('ar/create_invoice.html', title='Create Invoice', form=form)

            if unit_price is None:
                flash('Each invoice item must include a unit price.', 'danger')
                return render_template('ar/create_invoice.html', title='Create Invoice', form=form)

            amount = float(qty) * float(unit_price)
            subtotal += amount
            item_rows.append({
                'description': description,
                'quantity': qty,
                'unit': unit,
                'unit_price': unit_price,
                'amount': amount,
            })

        if not item_rows:
            flash('Add at least one invoice item.', 'danger')
            return render_template('ar/create_invoice.html', title='Create Invoice', form=form)

        tax = float(form.tax.data or 0)
        total = subtotal + tax

        invoice_number = _digits_only(form.number.data)
        if not invoice_number:
            flash('Invoice number must contain only numbers.', 'danger')
            return render_template('ar/create_invoice.html', title='Create Invoice', form=form)

        invoice = Invoice(
            number=invoice_number,
            date=form.date.data,
            due_date=(form.due_date.data or _compute_due_date(form.date.data, form.terms.data)),
            customer_id=form.customer_id.data,
            customer_po=(form.customer_po.data or '').strip() or None,
            rep=(form.rep.data or '').strip() or None,
            ship_date=form.ship_date.data,
            ship_via=(form.ship_via.data or '').strip() or None,
            fob=(form.fob.data or '').strip() or None,
            project=(form.project.data or '').strip() or None,
            bill_to_name=(form.bill_to_name.data or '').strip() or None,
            bill_to_address=(form.bill_to_address.data or '').strip() or None,
            ship_to_name=(form.ship_to_name.data or '').strip() or None,
            ship_to_address=(form.ship_to_address.data or '').strip() or None,
            authorized_signature=(form.authorized_signature.data or '').strip() or None,
            subtotal=subtotal,
            tax=tax,
            total=total,
            status='open',
            terms=form.terms.data,
            notes=form.notes.data,
            side_notes=form.side_notes.data,
        )
        db.session.add(invoice)

        for row in item_rows:
            inv_item = InvoiceItem(
                invoice=invoice,
                description=row['description'],
                quantity=row['quantity'],
                unit=row['unit'],
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

    form = QuoteForm()
    form.customer_id.choices = [(c.id, c.name) for c in customers]

    if request.method == 'GET':
        form.date.data = date.today()
        form.status.data = 'draft'
        if not form.customer_id.data:
            form.customer_id.data = customers[0].id

        selected = Customer.query.get(form.customer_id.data)
        if selected:
            if not (form.customer_tel.data or '').strip():
                form.customer_tel.data = selected.phone
            if not (form.customer_fax.data or '').strip():
                form.customer_fax.data = getattr(selected, 'fax', None)

    if form.validate_on_submit():
        if not form.due_date.data:
            computed = _compute_due_date(form.date.data, form.terms.data)
            if computed:
                form.due_date.data = computed
        item_rows = []
        subtotal = 0.0
        for item_form in form.items:
            description = (item_form.form.description.data or '').strip()
            qty = item_form.form.quantity.data
            unit = (item_form.form.unit.data or '').strip() or None
            unit_price = item_form.form.unit_price.data

            is_blank = (not description) and (qty is None) and (unit_price is None)
            if is_blank:
                continue

            if not description:
                flash('Each quote item must include a description.', 'danger')
                return render_template('ar/create_quote.html', title='Create Quote', form=form)

            if qty is None:
                flash('Each quote item must include a quantity.', 'danger')
                return render_template('ar/create_quote.html', title='Create Quote', form=form)

            if unit_price is None:
                flash('Each quote item must include a unit price.', 'danger')
                return render_template('ar/create_quote.html', title='Create Quote', form=form)

            amount = float(qty) * float(unit_price)
            subtotal += amount
            item_rows.append({
                'description': description,
                'quantity': qty,
                'unit': unit,
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
            due_date=form.due_date.data,
            valid_until=form.valid_until.data,
            customer_id=form.customer_id.data,
            project=(form.project.data or '').strip() or None,
            rep=(form.rep.data or '').strip() or None,
            customer_tel=(form.customer_tel.data or '').strip() or None,
            customer_fax=(form.customer_fax.data or '').strip() or None,
            subtotal=subtotal,
            tax=tax,
            total=total,
            status=form.status.data,
            terms=form.terms.data,
            notes=form.notes.data,
            printed_notes=form.printed_notes.data,
        )
        db.session.add(quote)

        for row in item_rows:
            q_item = QuoteItem(
                quote=quote,
                description=row['description'],
                quantity=row['quantity'],
                unit=row['unit'],
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

    form = QuoteForm(obj=quote)
    form.submit.label.text = 'Save Quote'
    form.customer_id.choices = [(c.id, c.name) for c in customers]

    if request.method == 'GET':
        form.customer_id.data = quote.customer_id
        existing_items = quote.items.order_by(QuoteItem.id.asc()).all()
        for idx, q_item in enumerate(existing_items[: len(form.items)]):
            form.items[idx].form.description.data = q_item.description
            form.items[idx].form.quantity.data = q_item.quantity
            form.items[idx].form.unit.data = q_item.unit
            form.items[idx].form.unit_price.data = q_item.unit_price

    if form.validate_on_submit():
        item_rows = []
        subtotal = 0.0
        for item_form in form.items:
            description = (item_form.form.description.data or '').strip()
            qty = item_form.form.quantity.data
            unit = (item_form.form.unit.data or '').strip() or None
            unit_price = item_form.form.unit_price.data

            is_blank = (not description) and (qty is None) and (unit_price is None)
            if is_blank:
                continue

            if not description:
                flash('Each quote item must include a description.', 'danger')
                return render_template('ar/edit_quote.html', title=f'Edit Quote {quote.number}', form=form, quote=quote)

            if qty is None:
                flash('Each quote item must include a quantity.', 'danger')
                return render_template('ar/edit_quote.html', title=f'Edit Quote {quote.number}', form=form, quote=quote)

            if unit_price is None:
                flash('Each quote item must include a unit price.', 'danger')
                return render_template('ar/edit_quote.html', title=f'Edit Quote {quote.number}', form=form, quote=quote)

            amount = float(qty) * float(unit_price)
            subtotal += amount
            item_rows.append({
                'description': description,
                'quantity': qty,
                'unit': unit,
                'unit_price': unit_price,
                'amount': amount,
            })

        if not item_rows:
            flash('Add at least one quote item.', 'danger')
            return render_template('ar/edit_quote.html', title=f'Edit Quote {quote.number}', form=form, quote=quote)

        tax = float(form.tax.data or 0)
        total = subtotal + tax

        quote.date = form.date.data
        quote.due_date = form.due_date.data
        quote.valid_until = form.valid_until.data
        quote.customer_id = form.customer_id.data
        quote.project = (form.project.data or '').strip() or None
        quote.rep = (form.rep.data or '').strip() or None
        quote.customer_tel = (form.customer_tel.data or '').strip() or None
        quote.customer_fax = (form.customer_fax.data or '').strip() or None
        quote.subtotal = subtotal
        quote.tax = tax
        quote.total = total
        quote.status = form.status.data
        quote.terms = form.terms.data
        quote.notes = form.notes.data
        quote.printed_notes = form.printed_notes.data

        existing_items = quote.items.all()
        for q_item in existing_items:
            db.session.delete(q_item)
        db.session.flush()

        for row in item_rows:
            q_item = QuoteItem(
                quote=quote,
                description=row['description'],
                quantity=row['quantity'],
                unit=row['unit'],
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
        project=(quote.project or '').strip() or None,
        rep=(quote.rep or '').strip() or None,
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
            description=q_item.description,
            quantity=q_item.quantity,
            unit=q_item.unit,
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

    form = InvoiceForm(obj=invoice)
    form.submit.label.text = 'Save Invoice'
    form.customer_id.choices = [(c.id, c.name) for c in customers]

    if request.method == 'GET':
        form.customer_id.data = invoice.customer_id
        existing_items = invoice.items.order_by(InvoiceItem.id.asc()).all()
        for idx, inv_item in enumerate(existing_items[: len(form.items)]):
            form.items[idx].form.description.data = inv_item.description
            form.items[idx].form.quantity.data = inv_item.quantity
            form.items[idx].form.unit.data = inv_item.unit
            form.items[idx].form.unit_price.data = inv_item.unit_price

    if form.validate_on_submit():
        invoice_number = _digits_only(form.number.data)
        if not invoice_number:
            flash('Invoice number must contain only numbers.', 'danger')
            return render_template('ar/edit_invoice.html', title=f'Edit Invoice {invoice.number}', form=form, invoice=invoice)

        item_rows = []
        subtotal = 0.0
        for item_form in form.items:
            description = (item_form.form.description.data or '').strip()
            qty = item_form.form.quantity.data
            unit = (item_form.form.unit.data or '').strip() or None
            unit_price = item_form.form.unit_price.data

            is_blank = (not description) and (qty is None) and (unit_price is None)
            if is_blank:
                continue

            if not description:
                flash('Each invoice item must include a description.', 'danger')
                return render_template('ar/edit_invoice.html', title=f'Edit Invoice {invoice.number}', form=form, invoice=invoice)

            if qty is None:
                flash('Each invoice item must include a quantity.', 'danger')
                return render_template('ar/edit_invoice.html', title=f'Edit Invoice {invoice.number}', form=form, invoice=invoice)

            if unit_price is None:
                flash('Each invoice item must include a unit price.', 'danger')
                return render_template('ar/edit_invoice.html', title=f'Edit Invoice {invoice.number}', form=form, invoice=invoice)

            amount = float(qty) * float(unit_price)
            subtotal += amount
            item_rows.append({
                'description': description,
                'quantity': qty,
                'unit': unit,
                'unit_price': unit_price,
                'amount': amount,
            })

        if not item_rows:
            flash('Add at least one invoice item.', 'danger')
            return render_template('ar/edit_invoice.html', title=f'Edit Invoice {invoice.number}', form=form, invoice=invoice)

        tax = float(form.tax.data or 0)
        total = subtotal + tax

        invoice.number = invoice_number
        invoice.date = form.date.data
        invoice.due_date = form.due_date.data
        invoice.customer_id = form.customer_id.data
        invoice.customer_po = (form.customer_po.data or '').strip() or None
        invoice.rep = (form.rep.data or '').strip() or None
        invoice.ship_date = form.ship_date.data
        invoice.ship_via = (form.ship_via.data or '').strip() or None
        invoice.fob = (form.fob.data or '').strip() or None
        invoice.project = (form.project.data or '').strip() or None
        invoice.bill_to_name = (form.bill_to_name.data or '').strip() or None
        invoice.bill_to_address = (form.bill_to_address.data or '').strip() or None
        invoice.ship_to_name = (form.ship_to_name.data or '').strip() or None
        invoice.ship_to_address = (form.ship_to_address.data or '').strip() or None
        invoice.authorized_signature = (form.authorized_signature.data or '').strip() or None
        invoice.subtotal = subtotal
        invoice.tax = tax
        invoice.total = total
        invoice.terms = form.terms.data
        invoice.notes = form.notes.data
        invoice.side_notes = form.side_notes.data

        existing_items = invoice.items.all()
        for inv_item in existing_items:
            db.session.delete(inv_item)
        db.session.flush()

        for row in item_rows:
            inv_item = InvoiceItem(
                invoice=invoice,
                description=row['description'],
                quantity=row['quantity'],
                unit=row['unit'],
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
        download_name=f"invoice_{invoice.number}.pdf",
    )


@bp.route('/quote/<int:id>/pdf')
@login_required
def quote_pdf(id):
    quote = Quote.query.get_or_404(id)
    items = quote.items.order_by(QuoteItem.id.asc()).all()
    pdf_data = _build_quote_pdf(quote, items)
    return send_file(
        BytesIO(pdf_data),
        mimetype='application/pdf',
        as_attachment=False,
        download_name=f"quote_{quote.number}.pdf",
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
