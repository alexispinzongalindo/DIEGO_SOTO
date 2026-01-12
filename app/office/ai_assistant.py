from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

import requests
from dateutil import parser
from flask import current_app, url_for
from fpdf import FPDF

from app import db
from app.auth.email import send_email_with_attachments_sync
from app.models import Bill, BillItem, Customer, Invoice, InvoiceItem, LibraryDocument, Meeting, Notification, Payment, Project, PurchaseOrder, PurchaseOrderItem, Quote, QuoteItem, User, Vendor
from app.office.library_storage import get_document_abs_path


def _utc_now() -> datetime:
    return datetime.utcnow()


def _is_es(lang: str) -> bool:
    return (lang or '').strip().lower().startswith('es')


def _normalize_name(value: str) -> str:
    value = (value or '').strip().lower()
    if not value:
        return ''
    value = unicodedata.normalize('NFKD', value)
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _find_customer_by_name(name: str) -> Optional[Customer]:
    raw = (name or '').strip()
    if not raw:
        return None

    direct = (
        Customer.query.filter(Customer.name.ilike(f"%{raw}%"))
        .order_by(Customer.name.asc())
        .first()
    )
    if direct:
        return direct

    normalized = _normalize_name(raw)
    if not normalized:
        return None

    if normalized != raw.lower():
        alt = (
            Customer.query.filter(Customer.name.ilike(f"%{normalized}%"))
            .order_by(Customer.name.asc())
            .first()
        )
        if alt:
            return alt

    tokens = [t for t in normalized.split(' ') if len(t) >= 2]
    if not tokens:
        return None

    q = Customer.query
    for t in tokens[:4]:
        q = q.filter(Customer.name.ilike(f"%{t}%"))
    token_match = q.order_by(Customer.name.asc()).first()
    if token_match:
        return token_match

    candidates = Customer.query.order_by(Customer.name.asc()).limit(500).all()
    for c in candidates:
        cn = _normalize_name(c.name or '')
        if cn and all(t in cn for t in tokens):
            return c
    return None


def _find_vendor_by_name(name: str) -> Optional[Vendor]:
    raw = (name or '').strip()
    if not raw:
        return None

    direct = (
        Vendor.query.filter(Vendor.name.ilike(f"%{raw}%"))
        .order_by(Vendor.name.asc())
        .first()
    )
    if direct:
        return direct

    normalized = _normalize_name(raw)
    if not normalized:
        return None

    if normalized != raw.lower():
        alt = (
            Vendor.query.filter(Vendor.name.ilike(f"%{normalized}%"))
            .order_by(Vendor.name.asc())
            .first()
        )
        if alt:
            return alt

    tokens = [t for t in normalized.split(' ') if len(t) >= 2]
    if not tokens:
        return None

    q = Vendor.query
    for t in tokens[:4]:
        q = q.filter(Vendor.name.ilike(f"%{t}%"))
    token_match = q.order_by(Vendor.name.asc()).first()
    if token_match:
        return token_match

    candidates = Vendor.query.order_by(Vendor.name.asc()).limit(500).all()
    for v in candidates:
        vn = _normalize_name(v.name or '')
        if vn and all(t in vn for t in tokens):
            return v
    return None


def _next_invoice_number() -> str:
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


def _next_quote_number() -> str:
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


def _next_bill_number() -> str:
    last = Bill.query.order_by(Bill.id.desc()).first()
    if not last or not last.number:
        return 'BILL-000001'
    try:
        raw = (last.number or '').strip().upper()
        if raw.startswith('BILL-'):
            n = int(raw.split('-', 1)[1])
        else:
            n = int(raw)
        return f"BILL-{n + 1:06d}"
    except Exception:
        return f"BILL-{(last.id + 1):06d}"


def _next_po_number() -> str:
    last = PurchaseOrder.query.order_by(PurchaseOrder.id.desc()).first()
    if not last or not last.number:
        return 'PO-000001'
    try:
        raw = (last.number or '').strip().upper()
        if raw.startswith('PO-'):
            n = int(raw.split('-', 1)[1])
        else:
            n = int(raw)
        return f"PO-{n + 1:06d}"
    except Exception:
        return f"PO-{(last.id + 1):06d}"


def _find_purchase_order_by_number_or_id(number_or_id: str) -> Optional[PurchaseOrder]:
    raw = (number_or_id or '').strip()
    if not raw:
        return None
    if raw.isdigit():
        return PurchaseOrder.query.get(int(raw))
    return PurchaseOrder.query.filter_by(number=raw).first()


def _extract_customer_name_for_balance(text: str, lang: str) -> Optional[str]:
    raw = (text or '').strip()
    if not raw:
        return None
    lower = raw.lower()
    markers = [
        'balance de ',
        'balance del ',
        'saldo de ',
        'saldo del ',
        "customer balance ",
        "balance for ",
    ]
    for m in markers:
        idx = lower.find(m)
        if idx >= 0:
            name = raw[idx + len(m):].strip()
            for trailing in ['?', '.', '!', ',']:
                if name.endswith(trailing):
                    name = name[:-1].strip()
            return name or None
    if _is_es(lang) and 'balance' in lower:
        name = raw.replace('balance', '').replace('Balance', '').strip(' :,-')
        return name or None
    return None


def _tool_meetings_today(lang: str) -> Dict[str, Any]:
    now = _utc_now()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)

    meetings = (
        Meeting.query.filter(Meeting.start_at >= start, Meeting.start_at < end)
        .order_by(Meeting.start_at.asc())
        .all()
    )

    if not meetings:
        return {
            'speak': 'No tienes reuniones hoy.' if _is_es(lang) else 'You have no meetings today.',
            'redirect_url': url_for('office.meetings'),
        }

    parts = []
    for m in meetings[:5]:
        parts.append(f"{m.title} at {m.start_at.strftime('%H:%M')}")

    speak = ('Hoy tienes: ' if _is_es(lang) else 'Today you have: ') + '; '.join(parts)
    return {'speak': speak, 'redirect_url': url_for('office.meetings')}


def _tool_overdue_invoices(lang: str) -> Dict[str, Any]:
    today = _utc_now().date()
    invoices = Invoice.query.filter(Invoice.due_date.isnot(None)).all()
    overdue = [inv for inv in invoices if inv.due_date and inv.due_date < today and inv.balance > 0.01]

    if not overdue:
        return {
            'speak': 'No tienes facturas vencidas.' if _is_es(lang) else 'You have no overdue invoices.',
            'redirect_url': url_for('ar.invoices'),
        }

    speak = f"Tienes {len(overdue)} facturas vencidas." if _is_es(lang) else f"You have {len(overdue)} overdue invoices."
    return {'speak': speak, 'redirect_url': url_for('ar.invoices')}


def _tool_payments_to_collect_this_week(lang: str) -> Dict[str, Any]:
    today = _utc_now().date()
    start = today
    end = today + timedelta(days=7)

    invoices = (
        Invoice.query.filter(Invoice.due_date.isnot(None))
        .filter(Invoice.due_date >= start)
        .filter(Invoice.due_date <= end)
        .all()
    )
    total_balance = sum((inv.balance or 0.0) for inv in invoices if (inv.balance or 0.0) > 0.01)
    count = sum(1 for inv in invoices if (inv.balance or 0.0) > 0.01)

    if _is_es(lang):
        speak = f"Esta semana debes cobrar aproximadamente ${total_balance:,.2f} en {count} facturas."
    else:
        speak = f"This week you should collect approximately ${total_balance:,.2f} across {count} invoices."

    return {'speak': speak, 'redirect_url': url_for('ar.invoices')}


def _tool_open_section(section: str, lang: str) -> Dict[str, Any]:
    section = (section or '').strip().lower()

    if section in ('agenda', 'meetings', 'calendario'):
        return {
            'speak': 'Abriendo agenda.' if _is_es(lang) else 'Opening agenda.',
            'redirect_url': url_for('office.meetings'),
        }
    if section in ('invoices', 'facturas'):
        return {
            'speak': 'Abriendo facturas.' if _is_es(lang) else 'Opening invoices.',
            'redirect_url': url_for('ar.invoices'),
        }
    if section in ('notifications', 'notificaciones'):
        return {
            'speak': 'Abriendo notificaciones.' if _is_es(lang) else 'Opening notifications.',
            'redirect_url': url_for('office.notifications'),
        }
    if section in ('dashboard', 'inicio', 'panel', 'tablero'):
        return {
            'speak': 'Abriendo tablero.' if _is_es(lang) else 'Opening dashboard.',
            'redirect_url': url_for('main.dashboard'),
        }

    return {'speak': 'No entendí qué abrir.' if _is_es(lang) else "I didn't understand what to open."}


def _parse_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parser.isoparse(value)
    except Exception:
        try:
            return parser.parse(value)
        except Exception:
            return None


def _tool_create_meeting(args: Dict[str, Any], user: User, lang: str) -> Dict[str, Any]:
    title = (args.get('title') or '').strip()
    if not title:
        return {'speak': 'Falta el título.' if _is_es(lang) else 'Missing title.'}

    start_at = _parse_dt((args.get('start_at') or '').strip())
    if not start_at:
        return {'speak': 'Falta la fecha/hora de inicio.' if _is_es(lang) else 'Missing start date/time.'}

    end_at = _parse_dt((args.get('end_at') or '').strip())

    reminder_minutes = args.get('reminder_minutes')
    try:
        reminder_minutes_int = int(reminder_minutes) if reminder_minutes is not None else 60
    except Exception:
        reminder_minutes_int = 60

    location = (args.get('location') or '').strip() or None
    notes = (args.get('notes') or '').strip() or None

    meeting = Meeting(
        title=title,
        start_at=start_at,
        end_at=end_at,
        location=location,
        notes=notes,
        reminder_minutes=reminder_minutes_int,
        created_by_id=user.id,
    )
    db.session.add(meeting)
    db.session.commit()

    return {
        'speak': 'Reunión creada.' if _is_es(lang) else 'Meeting created.',
        'redirect_url': url_for('office.meetings'),
    }


def _tool_list_customers(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    limit = args.get('limit')
    try:
        limit_int = int(limit) if limit is not None else 10
    except Exception:
        limit_int = 10
    limit_int = max(1, min(limit_int, 25))

    customers = Customer.query.order_by(Customer.name.asc()).limit(limit_int).all()
    if not customers:
        return {'speak': 'No hay clientes.' if _is_es(lang) else 'There are no customers.'}

    parts = [c.name for c in customers if c.name]
    speak = ('Clientes: ' if _is_es(lang) else 'Customers: ') + ', '.join(parts)
    return {'speak': speak, 'redirect_url': url_for('ar.customers')}


def _tool_create_customer(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    name = (args.get('name') or '').strip()
    if not name:
        return {'speak': 'Falta el nombre del cliente.' if _is_es(lang) else 'Missing customer name.'}

    existing = _find_customer_by_name(name)
    if existing:
        return {
            'speak': (f'El cliente {existing.name} ya existe.' if _is_es(lang) else f'Customer {existing.name} already exists.'),
            'redirect_url': url_for('ar.customers'),
        }

    email = (args.get('email') or '').strip() or None
    phone = (args.get('phone') or '').strip() or None
    address = (args.get('address') or '').strip() or None
    tax_id = (args.get('tax_id') or '').strip() or None

    credit_limit = args.get('credit_limit')
    credit_limit_val = None
    if credit_limit is not None and str(credit_limit).strip() != '':
        try:
            credit_limit_val = float(credit_limit)
        except Exception:
            credit_limit_val = None

    customer = Customer(
        name=name,
        email=email,
        phone=phone,
        address=address,
        tax_id=tax_id,
    )
    if credit_limit_val is not None:
        customer.credit_limit = credit_limit_val

    db.session.add(customer)
    db.session.commit()

    return {
        'speak': ('Cliente creado.' if _is_es(lang) else 'Customer created.'),
        'redirect_url': url_for('ar.customers'),
    }


def _format_questions(questions: list[str]) -> str:
    return "\n".join([f"{idx}. {q}" for idx, q in enumerate(questions, start=1)])


def _tool_create_invoice(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    customer_name = (args.get('customer_name') or '').strip()
    amount = args.get('amount')
    try:
        amount_val = float(amount)
    except Exception:
        amount_val = 0.0

    missing_questions = []
    if not customer_name:
        missing_questions.append('¿Cuál es el nombre del cliente?' if _is_es(lang) else 'What is the customer name?')
    if amount_val <= 0:
        missing_questions.append('¿Cuál es el monto?' if _is_es(lang) else 'What is the amount?')
    if missing_questions:
        return {'speak': _format_questions(missing_questions)}

    customer = _find_customer_by_name(customer_name)
    if not customer:
        return {
            'speak': 'No encontré ese cliente.' if _is_es(lang) else "I couldn't find that customer.",
            'redirect_url': url_for('ar.customers'),
        }

    description = (args.get('description') or '').strip() or ('Servicio' if _is_es(lang) else 'Service')

    inv_date_raw = (args.get('date') or '').strip()
    inv_date = None
    if inv_date_raw:
        try:
            inv_date = parser.parse(inv_date_raw).date()
        except Exception:
            inv_date = None
    if inv_date is None:
        inv_date = date.today()

    due_date_raw = (args.get('due_date') or '').strip()
    due_date = None
    if due_date_raw:
        try:
            due_date = parser.parse(due_date_raw).date()
        except Exception:
            due_date = None

    tax = args.get('tax')
    try:
        tax_val = float(tax) if tax is not None else 0.0
    except Exception:
        tax_val = 0.0
    tax_val = max(0.0, tax_val)

    subtotal = float(amount_val)
    total = float(subtotal + tax_val)

    invoice = Invoice(
        number=_next_invoice_number(),
        date=inv_date,
        due_date=due_date,
        customer_id=customer.id,
        subtotal=subtotal,
        tax=tax_val,
        total=total,
        status='open',
        terms=(args.get('terms') or '').strip() or None,
        notes=(args.get('notes') or '').strip() or None,
    )
    db.session.add(invoice)
    db.session.flush()

    item = InvoiceItem(
        invoice=invoice,
        product_id=None,
        description=description,
        quantity=1,
        unit_price=subtotal,
        amount=subtotal,
    )
    db.session.add(item)
    db.session.commit()

    if _is_es(lang):
        speak = f"Factura creada para {customer.name} por ${total:,.2f}."
    else:
        speak = f"Invoice created for {customer.name} for ${total:,.2f}."

    return {'speak': speak, 'redirect_url': url_for('ar.view_invoice', id=invoice.id)}


def _build_invoice_pdf(invoice: Invoice, items: list[InvoiceItem]) -> bytes:
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
        desc = item.description or ''
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


def _build_purchase_order_pdf(po: PurchaseOrder, items: list[PurchaseOrderItem]) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, 'Purchase Order', ln=True)

    pdf.set_font('Helvetica', '', 11)
    pdf.cell(0, 6, f"PO #: {po.number}", ln=True)
    pdf.cell(0, 6, f"PO Date: {po.date.strftime('%Y-%m-%d') if po.date else ''}", ln=True)
    if po.po_type == 'vendor' and po.vendor_id:
        vendor = Vendor.query.get(po.vendor_id)
        if vendor:
            pdf.cell(0, 6, f"Vendor: {vendor.name}", ln=True)
    if po.po_type == 'customer' and po.customer_id:
        customer = Customer.query.get(po.customer_id)
        if customer:
            pdf.cell(0, 6, f"Customer: {customer.name}", ln=True)
    pdf.ln(4)

    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(110, 8, 'Description', border=1)
    pdf.cell(20, 8, 'Qty', border=1, align='R')
    pdf.cell(30, 8, 'Unit Price', border=1, align='R')
    pdf.cell(30, 8, 'Amount', border=1, align='R')
    pdf.ln(8)

    pdf.set_font('Helvetica', '', 10)
    for item in items:
        desc = item.description or ''
        qty = float(item.quantity or 0)
        unit_price = float(item.unit_price or 0)
        amount = float(item.amount or 0)
        pdf.cell(110, 8, (desc[:55] + '...') if len(desc) > 58 else desc, border=1)
        pdf.cell(20, 8, f"{qty:g}", border=1, align='R')
        pdf.cell(30, 8, f"${unit_price:,.2f}", border=1, align='R')
        pdf.cell(30, 8, f"${amount:,.2f}", border=1, align='R')
        pdf.ln(8)

    pdf.ln(4)
    pdf.set_font('Helvetica', '', 11)
    subtotal = float(po.subtotal or 0)
    tax = float(po.tax or 0)
    total = float(po.total or 0)
    pdf.cell(160, 6, 'Subtotal', align='R')
    pdf.cell(30, 6, f"${subtotal:,.2f}", ln=True, align='R')
    pdf.cell(160, 6, 'Tax', align='R')
    pdf.cell(30, 6, f"${tax:,.2f}", ln=True, align='R')
    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(160, 7, 'Total', align='R')
    pdf.cell(30, 7, f"${total:,.2f}", ln=True, align='R')

    out = pdf.output(dest='S')
    if isinstance(out, str):
        out = out.encode('latin-1')
    return out


def _build_quote_pdf(quote: Quote, items: list[QuoteItem]) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, 'Quote', ln=True)

    pdf.set_font('Helvetica', '', 11)
    pdf.cell(0, 6, f"Quote #: {quote.number}", ln=True)
    pdf.cell(0, 6, f"Quote Date: {quote.date.strftime('%Y-%m-%d') if quote.date else ''}", ln=True)
    pdf.cell(0, 6, f"Valid Until: {quote.valid_until.strftime('%Y-%m-%d') if quote.valid_until else ''}", ln=True)
    if quote.customer:
        pdf.cell(0, 6, f"Customer: {quote.customer.name}", ln=True)
    pdf.ln(4)

    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(90, 8, 'Description', border=1)
    pdf.cell(20, 8, 'Qty', border=1, align='R')
    pdf.cell(30, 8, 'Unit Price', border=1, align='R')
    pdf.cell(30, 8, 'Amount', border=1, align='R')
    pdf.ln(8)

    pdf.set_font('Helvetica', '', 10)
    for item in items:
        desc = item.description or ''
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
    subtotal = float(quote.subtotal or 0)
    tax = float(quote.tax or 0)
    total = float(quote.total or 0)
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


def _find_quote_by_number_or_id(number_or_id: str) -> Optional[Quote]:
    number_or_id = (number_or_id or '').strip()
    if not number_or_id:
        return None
    quote = None
    if number_or_id.isdigit():
        quote = Quote.query.get(int(number_or_id))
    if quote is None:
        quote = Quote.query.filter_by(number=number_or_id).first()
    return quote


def _tool_create_quote(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    customer_name = (args.get('customer_name') or '').strip()
    amount = args.get('amount')
    try:
        amount_val = float(amount)
    except Exception:
        amount_val = 0.0

    missing_questions = []
    if not customer_name:
        missing_questions.append('¿Cuál es el nombre del cliente?' if _is_es(lang) else 'What is the customer name?')
    if amount_val <= 0:
        missing_questions.append('¿Cuál es el monto?' if _is_es(lang) else 'What is the amount?')
    if missing_questions:
        return {'speak': _format_questions(missing_questions)}

    customer = _find_customer_by_name(customer_name)
    if not customer:
        return {
            'speak': 'No encontré ese cliente.' if _is_es(lang) else "I couldn't find that customer.",
            'redirect_url': url_for('ar.customers'),
        }

    description = (args.get('description') or '').strip() or ('Servicio' if _is_es(lang) else 'Service')

    quote_date_raw = (args.get('date') or '').strip()
    quote_date = None
    if quote_date_raw:
        try:
            quote_date = parser.parse(quote_date_raw).date()
        except Exception:
            quote_date = None
    if quote_date is None:
        quote_date = date.today()

    valid_until_raw = (args.get('valid_until') or '').strip()
    valid_until = None
    if valid_until_raw:
        try:
            valid_until = parser.parse(valid_until_raw).date()
        except Exception:
            valid_until = None

    tax = args.get('tax')
    try:
        tax_val = float(tax) if tax is not None else 0.0
    except Exception:
        tax_val = 0.0
    tax_val = max(0.0, tax_val)

    subtotal = float(amount_val)
    total = float(subtotal + tax_val)

    quote = Quote(
        number=_next_quote_number(),
        date=quote_date,
        valid_until=valid_until,
        customer_id=customer.id,
        subtotal=subtotal,
        tax=tax_val,
        total=total,
        status=(args.get('status') or '').strip() or 'draft',
        terms=(args.get('terms') or '').strip() or None,
        notes=(args.get('notes') or '').strip() or None,
    )
    db.session.add(quote)
    db.session.flush()

    item = QuoteItem(
        quote=quote,
        product_id=None,
        description=description,
        quantity=1,
        unit_price=subtotal,
        amount=subtotal,
    )
    db.session.add(item)
    db.session.commit()

    if _is_es(lang):
        speak = f"Cotización creada para {customer.name} por ${total:,.2f}."
    else:
        speak = f"Quote created for {customer.name} for ${total:,.2f}."

    return {'speak': speak, 'redirect_url': url_for('ar.view_quote', id=quote.id)}


def _tool_create_bill(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    vendor_name = (args.get('vendor_name') or '').strip()

    amount = args.get('amount')
    try:
        amount_val = float(amount)
    except Exception:
        amount_val = 0.0

    missing_questions = []
    if not vendor_name:
        missing_questions.append('¿Cuál es el nombre del proveedor?' if _is_es(lang) else 'What is the vendor name?')
    if amount_val <= 0:
        missing_questions.append('¿Cuál es el monto?' if _is_es(lang) else 'What is the amount?')
    if missing_questions:
        return {'speak': _format_questions(missing_questions)}

    vendor = _find_vendor_by_name(vendor_name)
    if not vendor:
        return {
            'speak': 'No encontré ese proveedor.' if _is_es(lang) else "I couldn't find that vendor.",
            'redirect_url': url_for('ap.vendors'),
        }

    description = (args.get('description') or '').strip() or ('Servicio' if _is_es(lang) else 'Service')

    bill_date_raw = (args.get('date') or '').strip()
    bill_date = None
    if bill_date_raw:
        try:
            bill_date = parser.parse(bill_date_raw).date()
        except Exception:
            bill_date = None
    if bill_date is None:
        bill_date = date.today()

    due_date_raw = (args.get('due_date') or '').strip()
    due_date = None
    if due_date_raw:
        try:
            due_date = parser.parse(due_date_raw).date()
        except Exception:
            due_date = None

    tax = args.get('tax')
    try:
        tax_val = float(tax) if tax is not None else 0.0
    except Exception:
        tax_val = 0.0
    tax_val = max(0.0, tax_val)

    subtotal = float(amount_val)
    total = float(subtotal + tax_val)

    bill = Bill(
        number=_next_bill_number(),
        date=bill_date,
        due_date=due_date,
        vendor_id=vendor.id,
        subtotal=subtotal,
        tax=tax_val,
        total=total,
        status='open',
        terms=(args.get('terms') or '').strip() or None,
        notes=(args.get('notes') or '').strip() or None,
    )
    db.session.add(bill)
    db.session.flush()

    db.session.add(
        BillItem(
            bill=bill,
            product_id=None,
            description=description,
            quantity=1,
            unit_price=subtotal,
            amount=subtotal,
        )
    )
    db.session.commit()

    if _is_es(lang):
        speak = f"Cuenta creada para {vendor.name} por ${total:,.2f}."
    else:
        speak = f"Bill created for {vendor.name} for ${total:,.2f}."

    return {'speak': speak, 'redirect_url': url_for('ap.view_bill', id=bill.id)}


def _tool_create_purchase_order(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    po_type = (args.get('po_type') or '').strip().lower()
    if po_type not in ('vendor', 'customer'):
        po_type = ''

    vendor_name = (args.get('vendor_name') or '').strip()
    customer_name = (args.get('customer_name') or '').strip()

    amount = args.get('amount')
    try:
        amount_val = float(amount)
    except Exception:
        amount_val = 0.0

    missing_questions = []
    if not po_type:
        missing_questions.append('¿Es para proveedor o cliente? (vendor/customer)' if _is_es(lang) else 'Is this for a vendor or a customer? (vendor/customer)')
    if po_type == 'vendor' and not vendor_name:
        missing_questions.append('¿Cuál es el nombre del proveedor?' if _is_es(lang) else 'What is the vendor name?')
    if po_type == 'customer' and not customer_name:
        missing_questions.append('¿Cuál es el nombre del cliente?' if _is_es(lang) else 'What is the customer name?')
    if amount_val <= 0:
        missing_questions.append('¿Cuál es el monto?' if _is_es(lang) else 'What is the amount?')
    if missing_questions:
        return {'speak': _format_questions(missing_questions)}

    vendor_id = None
    customer_id = None
    if po_type == 'vendor':
        vendor = _find_vendor_by_name(vendor_name)
        if not vendor:
            return {
                'speak': 'No encontré ese proveedor.' if _is_es(lang) else "I couldn't find that vendor.",
                'redirect_url': url_for('ap.vendors'),
            }
        vendor_id = vendor.id
    else:
        customer = _find_customer_by_name(customer_name)
        if not customer:
            return {
                'speak': 'No encontré ese cliente.' if _is_es(lang) else "I couldn't find that customer.",
                'redirect_url': url_for('ar.customers'),
            }
        customer_id = customer.id

    description = (args.get('description') or '').strip() or ('Servicio' if _is_es(lang) else 'Service')

    po_date_raw = (args.get('date') or '').strip()
    po_date = None
    if po_date_raw:
        try:
            po_date = parser.parse(po_date_raw).date()
        except Exception:
            po_date = None
    if po_date is None:
        po_date = date.today()

    tax = args.get('tax')
    try:
        tax_val = float(tax) if tax is not None else 0.0
    except Exception:
        tax_val = 0.0
    tax_val = max(0.0, tax_val)

    subtotal = float(amount_val)
    total = float(subtotal + tax_val)

    po = PurchaseOrder(
        number=_next_po_number(),
        po_type=po_type,
        date=po_date,
        vendor_id=vendor_id,
        customer_id=customer_id,
        subtotal=subtotal,
        tax=tax_val,
        total=total,
        status=(args.get('status') or '').strip() or 'draft',
        terms=(args.get('terms') or '').strip() or None,
        notes=(args.get('notes') or '').strip() or None,
    )
    db.session.add(po)
    db.session.flush()

    db.session.add(
        PurchaseOrderItem(
            purchase_order=po,
            description=description,
            quantity=1,
            unit_price=subtotal,
            amount=subtotal,
        )
    )
    db.session.commit()

    if _is_es(lang):
        speak = f"Orden de compra creada {po.number} por ${total:,.2f}."
    else:
        speak = f"Purchase order created {po.number} for ${total:,.2f}."

    return {'speak': speak, 'redirect_url': url_for('po.view_purchase_order', id=po.id)}


def _tool_edit_quote(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    number_or_id = (args.get('number_or_id') or '').strip()
    if not number_or_id:
        return {'speak': 'Falta el número de cotización.' if _is_es(lang) else 'Missing quote number.'}

    quote = _find_quote_by_number_or_id(number_or_id)
    if not quote:
        return {'speak': 'No encontré esa cotización.' if _is_es(lang) else "I couldn't find that quote.", 'redirect_url': url_for('ar.quotes')}

    if quote.invoice_id:
        return {
            'speak': 'Esa cotización ya fue facturada y no se puede editar.' if _is_es(lang) else 'That quote has already been invoiced and cannot be edited.',
            'redirect_url': url_for('ar.view_quote', id=quote.id),
        }

    customer_name = (args.get('customer_name') or '').strip()
    if customer_name:
        customer = _find_customer_by_name(customer_name)
        if not customer:
            return {'speak': 'No encontré ese cliente.' if _is_es(lang) else "I couldn't find that customer.", 'redirect_url': url_for('ar.customers')}
        quote.customer_id = customer.id

    quote_date_raw = (args.get('date') or '').strip()
    if quote_date_raw:
        try:
            quote.date = parser.parse(quote_date_raw).date()
        except Exception:
            pass

    valid_until_raw = (args.get('valid_until') or '').strip()
    if valid_until_raw:
        try:
            quote.valid_until = parser.parse(valid_until_raw).date()
        except Exception:
            pass

    status = (args.get('status') or '').strip()
    if status:
        quote.status = status

    terms = args.get('terms')
    if terms is not None:
        quote.terms = (terms or '').strip() or None

    notes = args.get('notes')
    if notes is not None:
        quote.notes = (notes or '').strip() or None

    amount = args.get('amount')
    tax = args.get('tax')

    should_reprice = amount is not None or tax is not None or args.get('description') is not None
    if should_reprice:
        try:
            amount_val = float(amount) if amount is not None else float(quote.subtotal or 0)
        except Exception:
            amount_val = float(quote.subtotal or 0)
        try:
            tax_val = float(tax) if tax is not None else float(quote.tax or 0)
        except Exception:
            tax_val = float(quote.tax or 0)

        amount_val = max(0.0, amount_val)
        tax_val = max(0.0, tax_val)
        quote.subtotal = amount_val
        quote.tax = tax_val
        quote.total = float(amount_val + tax_val)

        description = (args.get('description') or '').strip()
        existing_items = quote.items.order_by(QuoteItem.id.asc()).all()
        if existing_items:
            first = existing_items[0]
            if description:
                first.description = description
            first.quantity = 1
            first.unit_price = amount_val
            first.amount = amount_val
            for extra in existing_items[1:]:
                db.session.delete(extra)
        else:
            if not description:
                description = 'Servicio' if _is_es(lang) else 'Service'
            db.session.add(
                QuoteItem(
                    quote=quote,
                    product_id=None,
                    description=description,
                    quantity=1,
                    unit_price=amount_val,
                    amount=amount_val,
                )
            )

    db.session.commit()

    return {
        'speak': 'Cotización actualizada.' if _is_es(lang) else 'Quote updated.',
        'redirect_url': url_for('ar.view_quote', id=quote.id),
    }


def _tool_delete_quote(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    number_or_id = (args.get('number_or_id') or '').strip()
    confirm = bool(args.get('confirm'))

    if not number_or_id:
        return {'speak': 'Falta el número de cotización.' if _is_es(lang) else 'Missing quote number.'}

    quote = _find_quote_by_number_or_id(number_or_id)
    if not quote:
        return {'speak': 'No encontré esa cotización.' if _is_es(lang) else "I couldn't find that quote.", 'redirect_url': url_for('ar.quotes')}

    if quote.invoice_id:
        return {
            'speak': 'No se puede borrar una cotización ya facturada.' if _is_es(lang) else 'Cannot delete a quote that has been invoiced.',
            'redirect_url': url_for('ar.view_quote', id=quote.id),
        }

    if not confirm:
        if _is_es(lang):
            speak = f"Confirmar: ¿Quieres borrar la cotización {quote.number}? Repite y di confirm=true."
        else:
            speak = f"Confirmation needed: delete quote {quote.number}? Repeat with confirm=true."
        return {'speak': speak, 'redirect_url': url_for('ar.view_quote', id=quote.id)}

    items = quote.items.all()
    for q_item in items:
        db.session.delete(q_item)
    db.session.delete(quote)
    db.session.commit()
    return {'speak': 'Cotización borrada.' if _is_es(lang) else 'Quote deleted.', 'redirect_url': url_for('ar.quotes')}


def _tool_convert_quote_to_invoice(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    number_or_id = (args.get('number_or_id') or '').strip()
    confirm = bool(args.get('confirm'))

    if not number_or_id:
        return {'speak': 'Falta el número de cotización.' if _is_es(lang) else 'Missing quote number.'}

    quote = _find_quote_by_number_or_id(number_or_id)
    if not quote:
        return {'speak': 'No encontré esa cotización.' if _is_es(lang) else "I couldn't find that quote.", 'redirect_url': url_for('ar.quotes')}

    if quote.invoice_id:
        return {
            'speak': 'Esa cotización ya fue convertida.' if _is_es(lang) else 'That quote has already been converted.',
            'redirect_url': url_for('ar.view_invoice', id=quote.invoice_id),
        }

    item_list = quote.items.order_by(QuoteItem.id.asc()).all()
    if not item_list:
        return {'speak': 'No se puede convertir una cotización sin artículos.' if _is_es(lang) else 'Cannot convert a quote with no items.', 'redirect_url': url_for('ar.view_quote', id=quote.id)}

    if not confirm:
        if _is_es(lang):
            speak = f"Confirmar: ¿Quieres convertir la cotización {quote.number} a factura? Repite y di confirm=true."
        else:
            speak = f"Confirmation needed: convert quote {quote.number} to an invoice? Repeat with confirm=true."
        return {'speak': speak, 'redirect_url': url_for('ar.view_quote', id=quote.id)}

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
    db.session.flush()

    for q_item in item_list:
        db.session.add(
            InvoiceItem(
                invoice=invoice,
                product_id=None,
                description=q_item.description,
                quantity=q_item.quantity,
                unit_price=q_item.unit_price,
                amount=q_item.amount,
            )
        )

    quote.invoice = invoice
    quote.status = 'invoiced'
    db.session.commit()

    if _is_es(lang):
        speak = f"Cotización {quote.number} convertida a factura {invoice.number}."
    else:
        speak = f"Quote {quote.number} converted to invoice {invoice.number}."
    return {'speak': speak, 'redirect_url': url_for('ar.view_invoice', id=invoice.id)}


def _tool_email_quote(args: Dict[str, Any], user: User, lang: str) -> Dict[str, Any]:
    number_or_id = (args.get('number_or_id') or '').strip()
    to_email = (args.get('to_email') or '').strip()
    to_name = (args.get('to_name') or '').strip()
    message = (args.get('message') or '').strip()
    confirm = bool(args.get('confirm'))
    save_contact = bool(args.get('save_contact'))

    if not number_or_id:
        return {'speak': 'Falta el número de cotización.' if _is_es(lang) else 'Missing quote number.'}

    quote = _find_quote_by_number_or_id(number_or_id)
    if not quote:
        return {'speak': 'No encontré esa cotización.' if _is_es(lang) else "I couldn't find that quote.", 'redirect_url': url_for('ar.quotes')}

    if not to_email and quote.customer and quote.customer.email:
        to_email = (quote.customer.email or '').strip()

    if not to_email:
        contact_name = (quote.customer.name if quote.customer else '').strip() or (quote.number or number_or_id)
        if _is_es(lang):
            speak = (
                f"Necesito el correo para enviar la cotización {quote.number}.\n"
                f"1. ¿Cuál es el correo de {contact_name}?\n"
                "2. ¿Quieres guardarlo en el perfil del cliente? (sí/no)"
            )
        else:
            speak = (
                f"I need an email address to send quote {quote.number}.\n"
                f"1. What is {contact_name}'s email?\n"
                "2. Do you want me to save it on the customer profile? (yes/no)"
            )
        return {'speak': speak, 'redirect_url': url_for('ar.view_quote', id=quote.id)}

    if not confirm:
        if _is_es(lang):
            speak = f"Confirmar: ¿Quieres enviar la cotización {quote.number} a {to_email}?"
        else:
            speak = f"Confirmation needed: email quote {quote.number} to {to_email}?"
        return {'speak': speak, 'redirect_url': url_for('ar.view_quote', id=quote.id), 'needs_confirm': True}

    items = quote.items.order_by(QuoteItem.id.asc()).all()
    pdf_bytes = _build_quote_pdf(quote, items)

    subject = f"Quote {quote.number or quote.id}"
    text_body = message or ('Adjunto la cotización.' if _is_es(lang) else 'Attached is the quote.')
    html_body = f"<p>{text_body}</p>"
    sender = (
        (current_app.config.get('MAIL_DEFAULT_SENDER') or '').strip()
        or (user.email or '').strip()
        or 'noreply@example.com'
    )

    send_email_with_attachments_sync(
        subject=subject,
        sender=sender,
        recipients=[to_email],
        text_body=text_body,
        html_body=html_body,
        attachments=[(f"{quote.number or 'quote'}.pdf", 'application/pdf', pdf_bytes)],
    )

    if save_contact and quote.customer and to_email:
        current = (quote.customer.email or '').strip()
        if current != to_email:
            quote.customer.email = to_email
            db.session.commit()

    return {
        'speak': 'Correo enviado.' if _is_es(lang) else 'Email sent.',
        'redirect_url': url_for('ar.view_quote', id=quote.id),
    }


def _tool_email_invoice(args: Dict[str, Any], user: User, lang: str) -> Dict[str, Any]:
    number_or_id = (args.get('number_or_id') or '').strip()
    to_email = (args.get('to_email') or '').strip()
    to_name = (args.get('to_name') or '').strip()
    message = (args.get('message') or '').strip()
    confirm = bool(args.get('confirm'))
    save_contact = bool(args.get('save_contact'))

    if not number_or_id:
        return {'speak': 'Falta el número de factura.' if _is_es(lang) else 'Missing invoice number.'}

    invoice = None
    if number_or_id.isdigit():
        invoice = Invoice.query.get(int(number_or_id))
    if invoice is None:
        invoice = Invoice.query.filter_by(number=number_or_id).first()

    if invoice is None:
        return {'speak': 'No encontré esa factura.' if _is_es(lang) else "I couldn't find that invoice.", 'redirect_url': url_for('ar.invoices')}

    if not to_email and to_name:
        customer = _find_customer_by_name(to_name)
        if customer and customer.email:
            to_email = (customer.email or '').strip()

    if not to_email and invoice.customer and invoice.customer.email:
        to_email = (invoice.customer.email or '').strip()

    if not to_email:
        contact_name = (invoice.customer.name if invoice.customer else '').strip() or (invoice.number or number_or_id)
        if _is_es(lang):
            speak = (
                f"Necesito el correo para enviar la factura {invoice.number}.\n"
                f"1. ¿Cuál es el correo de {contact_name}?\n"
                "2. ¿Quieres guardarlo en el perfil del cliente? (sí/no)"
            )
        else:
            speak = (
                f"I need an email address to send invoice {invoice.number}.\n"
                f"1. What is {contact_name}'s email?\n"
                "2. Do you want me to save it on the customer profile? (yes/no)"
            )
        return {'speak': speak, 'redirect_url': url_for('ar.view_invoice', id=invoice.id)}

    if not confirm:
        if _is_es(lang):
            speak = f"Confirmar: ¿Quieres enviar la factura {invoice.number} a {to_email}?"
        else:
            speak = f"Confirmation needed: email invoice {invoice.number} to {to_email}?"
        return {'speak': speak, 'redirect_url': url_for('ar.view_invoice', id=invoice.id), 'needs_confirm': True}

    items = InvoiceItem.query.filter_by(invoice_id=invoice.id).order_by(InvoiceItem.id.asc()).all()
    pdf_bytes = _build_invoice_pdf(invoice, items)

    subject = f"Invoice {invoice.number or invoice.id}"
    text_body = message or ('Adjunto la factura.' if _is_es(lang) else 'Attached is the invoice.')
    html_body = f"<p>{text_body}</p>"
    sender = (
        (current_app.config.get('MAIL_DEFAULT_SENDER') or '').strip()
        or (user.email or '').strip()
        or 'noreply@example.com'
    )

    send_email_with_attachments_sync(
        subject=subject,
        sender=sender,
        recipients=[to_email],
        text_body=text_body,
        html_body=html_body,
        attachments=[(f"{invoice.number or 'invoice'}.pdf", 'application/pdf', pdf_bytes)],
    )

    if save_contact and invoice.customer and to_email:
        current = (invoice.customer.email or '').strip()
        if current != to_email:
            invoice.customer.email = to_email
            db.session.commit()

    return {
        'speak': 'Correo enviado.' if _is_es(lang) else 'Email sent.',
        'redirect_url': url_for('ar.view_invoice', id=invoice.id),
    }


def _tool_email_purchase_order(args: Dict[str, Any], user: User, lang: str) -> Dict[str, Any]:
    number_or_id = (args.get('number_or_id') or '').strip()
    to_email = (args.get('to_email') or '').strip()
    to_name = (args.get('to_name') or '').strip()
    message = (args.get('message') or '').strip()
    confirm = bool(args.get('confirm'))
    save_contact = bool(args.get('save_contact'))

    if not number_or_id:
        return {'speak': 'Falta el número de orden de compra.' if _is_es(lang) else 'Missing purchase order number.'}

    po = _find_purchase_order_by_number_or_id(number_or_id)
    if not po:
        return {'speak': 'No encontré esa orden de compra.' if _is_es(lang) else "I couldn't find that purchase order.", 'redirect_url': url_for('po.purchase_orders')}

    po_customer = Customer.query.get(po.customer_id) if po.customer_id else None
    po_vendor = Vendor.query.get(po.vendor_id) if po.vendor_id else None
    po_contact = po_vendor if po.po_type == 'vendor' else po_customer

    if not to_email and to_name:
        if po.po_type == 'vendor':
            vendor = _find_vendor_by_name(to_name)
            if vendor and vendor.email:
                to_email = (vendor.email or '').strip()
        else:
            customer = _find_customer_by_name(to_name)
            if customer and customer.email:
                to_email = (customer.email or '').strip()

    if not to_email and po_contact and po_contact.email:
        to_email = (po_contact.email or '').strip()

    if not to_email:
        contact_name = (po_contact.name if po_contact else '').strip() or (po.number or number_or_id)
        if _is_es(lang):
            speak = (
                f"Necesito el correo para enviar la orden de compra {po.number}.\n"
                f"1. ¿Cuál es el correo de {contact_name}?\n"
                "2. ¿Quieres guardarlo en el perfil? (sí/no)"
            )
        else:
            speak = (
                f"I need an email address to send purchase order {po.number}.\n"
                f"1. What is {contact_name}'s email?\n"
                "2. Do you want me to save it on the profile? (yes/no)"
            )
        return {'speak': speak, 'redirect_url': url_for('po.view_purchase_order', id=po.id)}

    if not confirm:
        if _is_es(lang):
            speak = f"Confirmar: ¿Quieres enviar la orden de compra {po.number} a {to_email}?"
        else:
            speak = f"Confirmation needed: email purchase order {po.number} to {to_email}?"
        return {'speak': speak, 'redirect_url': url_for('po.view_purchase_order', id=po.id), 'needs_confirm': True}

    items = PurchaseOrderItem.query.filter_by(purchase_order_id=po.id).order_by(PurchaseOrderItem.id.asc()).all()
    pdf_bytes = _build_purchase_order_pdf(po, items)

    subject = f"Purchase Order {po.number or po.id}"
    text_body = message or ('Adjunto la orden de compra.' if _is_es(lang) else 'Attached is the purchase order.')
    html_body = f"<p>{text_body}</p>"
    sender = (
        (current_app.config.get('MAIL_DEFAULT_SENDER') or '').strip()
        or (user.email or '').strip()
        or 'noreply@example.com'
    )

    send_email_with_attachments_sync(
        subject=subject,
        sender=sender,
        recipients=[to_email],
        text_body=text_body,
        html_body=html_body,
        attachments=[(f"{po.number or 'purchase-order'}.pdf", 'application/pdf', pdf_bytes)],
    )

    if save_contact and po_contact and to_email:
        current = (po_contact.email or '').strip()
        if current != to_email:
            po_contact.email = to_email
            db.session.commit()

    return {
        'speak': 'Correo enviado.' if _is_es(lang) else 'Email sent.',
        'redirect_url': url_for('po.view_purchase_order', id=po.id),
    }


def _tool_record_payment(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    customer_name = (args.get('customer_name') or '').strip()
    if not customer_name:
        return {'speak': 'Falta el nombre del cliente.' if _is_es(lang) else 'Missing customer name.'}

    amount = args.get('amount')
    try:
        amount_val = float(amount)
    except Exception:
        amount_val = 0.0
    if amount_val <= 0:
        return {'speak': 'Falta el monto.' if _is_es(lang) else 'Missing amount.'}

    customer = _find_customer_by_name(customer_name)
    if not customer:
        return {'speak': 'No encontré ese cliente.' if _is_es(lang) else "I couldn't find that customer.", 'redirect_url': url_for('ar.customers')}

    pay_date_raw = (args.get('date') or '').strip()
    pay_date = None
    if pay_date_raw:
        try:
            pay_date = parser.parse(pay_date_raw).date()
        except Exception:
            pay_date = None
    if pay_date is None:
        pay_date = date.today()

    payment = Payment(
        date=pay_date,
        customer_id=customer.id,
        invoice_id=None,
        amount=amount_val,
        payment_method=(args.get('payment_method') or '').strip() or None,
        reference=(args.get('reference') or '').strip() or None,
        notes=(args.get('notes') or '').strip() or None,
    )
    db.session.add(payment)
    db.session.commit()

    if _is_es(lang):
        speak = f"Pago registrado para {customer.name} por ${amount_val:,.2f}."
    else:
        speak = f"Payment recorded for {customer.name} for ${amount_val:,.2f}."
    return {'speak': speak, 'redirect_url': url_for('ar.view_customer', id=customer.id)}


def _tool_customer_balance(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    name = (args.get('customer_name') or '').strip()
    if not name:
        return {'speak': 'Falta el nombre del cliente.' if _is_es(lang) else 'Missing customer name.'}

    customer = _find_customer_by_name(name)
    if not customer:
        return {'speak': 'No encontré ese cliente.' if _is_es(lang) else "I couldn't find that customer.", 'redirect_url': url_for('ar.customers')}

    invoices = Invoice.query.filter_by(customer_id=customer.id).order_by(Invoice.date.desc()).limit(500).all()
    open_invoices = [inv for inv in invoices if (inv.balance or 0.0) > 0.01]
    open_balance = float(sum((inv.balance or 0.0) for inv in open_invoices))

    if _is_es(lang):
        speak = f"El balance abierto de {customer.name} es ${open_balance:,.2f} en {len(open_invoices)} facturas."
    else:
        speak = f"{customer.name}'s open balance is ${open_balance:,.2f} across {len(open_invoices)} invoices."

    return {'speak': speak, 'redirect_url': url_for('ar.customers')}


def _tool_list_open_invoices(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    limit = args.get('limit')
    try:
        limit_int = int(limit) if limit is not None else 10
    except Exception:
        limit_int = 10
    limit_int = max(1, min(limit_int, 25))

    invoices = Invoice.query.order_by(Invoice.date.desc()).limit(200).all()
    open_invoices = [inv for inv in invoices if (inv.balance or 0.0) > 0.01]
    open_invoices = open_invoices[:limit_int]

    if not open_invoices:
        return {'speak': 'No hay facturas abiertas.' if _is_es(lang) else 'There are no open invoices.', 'redirect_url': url_for('ar.invoices')}

    parts = []
    for inv in open_invoices:
        num = inv.number or f"#{inv.id}"
        cust = getattr(inv.customer, 'name', None) if getattr(inv, 'customer', None) else None
        bal = float(inv.balance or 0.0)
        if cust:
            parts.append(f"{num} ({cust}) balance ${bal:,.2f}")
        else:
            parts.append(f"{num} balance ${bal:,.2f}")

    speak = ('Facturas abiertas: ' if _is_es(lang) else 'Open invoices: ') + '; '.join(parts)
    return {'speak': speak, 'redirect_url': url_for('ar.invoices')}


def _tool_invoice_summary(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    number_or_id = (args.get('number_or_id') or '').strip()
    invoice = None
    if number_or_id.isdigit():
        invoice = Invoice.query.get(int(number_or_id))
    if invoice is None and number_or_id:
        invoice = Invoice.query.filter_by(number=number_or_id).first()

    if invoice is None:
        return {'speak': 'No encontré esa factura.' if _is_es(lang) else "I couldn't find that invoice.", 'redirect_url': url_for('ar.invoices')}

    num = invoice.number or f"#{invoice.id}"
    total = float(invoice.total or 0.0)
    bal = float(invoice.balance or 0.0)
    status = invoice.status or 'open'
    cust = getattr(invoice.customer, 'name', None) if getattr(invoice, 'customer', None) else None

    if _is_es(lang):
        speak = f"Factura {num}" + (f" de {cust}" if cust else '') + f": total ${total:,.2f}, saldo ${bal:,.2f}, estado {status}."
    else:
        speak = f"Invoice {num}" + (f" for {cust}" if cust else '') + f": total ${total:,.2f}, balance ${bal:,.2f}, status {status}."
    return {'speak': speak, 'redirect_url': url_for('ar.invoices')}


def _tool_list_quotes(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    limit = args.get('limit')
    try:
        limit_int = int(limit) if limit is not None else 10
    except Exception:
        limit_int = 10
    limit_int = max(1, min(limit_int, 25))

    quotes = Quote.query.order_by(Quote.date.desc()).limit(limit_int).all()
    if not quotes:
        return {'speak': 'No hay cotizaciones.' if _is_es(lang) else 'There are no quotes.', 'redirect_url': url_for('ar.quotes')}

    parts = []
    for q in quotes:
        num = q.number or f"#{q.id}"
        cust = getattr(q.customer, 'name', None) if getattr(q, 'customer', None) else None
        total = float(q.total or 0.0)
        st = q.status or 'draft'
        if cust:
            parts.append(f"{num} ({cust}) ${total:,.2f} {st}")
        else:
            parts.append(f"{num} ${total:,.2f} {st}")

    speak = ('Cotizaciones: ' if _is_es(lang) else 'Quotes: ') + '; '.join(parts)
    return {'speak': speak, 'redirect_url': url_for('ar.quotes')}


def _tool_list_bills(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    limit = args.get('limit')
    try:
        limit_int = int(limit) if limit is not None else 10
    except Exception:
        limit_int = 10
    limit_int = max(1, min(limit_int, 25))

    bills = Bill.query.order_by(Bill.date.desc()).limit(limit_int).all()
    if not bills:
        return {'speak': 'No hay cuentas por pagar.' if _is_es(lang) else 'There are no bills.', 'redirect_url': url_for('ap.bills')}

    parts = []
    for b in bills:
        num = b.number or f"#{b.id}"
        vendor = getattr(b.vendor, 'name', None) if getattr(b, 'vendor', None) else None
        total = float(b.total or 0.0)
        bal = float(b.balance or 0.0)
        st = b.status or 'open'
        label = f"{num}"
        if vendor:
            label += f" ({vendor})"
        parts.append(f"{label} total ${total:,.2f} balance ${bal:,.2f} {st}")

    speak = ('Cuentas: ' if _is_es(lang) else 'Bills: ') + '; '.join(parts)
    return {'speak': speak, 'redirect_url': url_for('ap.bills')}


def _tool_list_unread_notifications(args: Dict[str, Any], user: User, lang: str) -> Dict[str, Any]:
    limit = args.get('limit')
    try:
        limit_int = int(limit) if limit is not None else 10
    except Exception:
        limit_int = 10
    limit_int = max(1, min(limit_int, 25))

    notifs = (
        Notification.query.filter_by(user_id=user.id)
        .filter(Notification.read_at.is_(None))
        .order_by(Notification.created_at.desc())
        .limit(limit_int)
        .all()
    )
    if not notifs:
        return {'speak': 'No tienes notificaciones nuevas.' if _is_es(lang) else 'You have no new notifications.', 'redirect_url': url_for('office.notifications')}

    parts = []
    for n in notifs:
        title = (n.title or '').strip() or (n.type or 'notification')
        parts.append(title)

    speak = ('Notificaciones: ' if _is_es(lang) else 'Notifications: ') + '; '.join(parts)
    return {'speak': speak, 'redirect_url': url_for('office.notifications')}


def _tool_mark_all_notifications_read(args: Dict[str, Any], user: User, lang: str) -> Dict[str, Any]:
    now = _utc_now()
    q = Notification.query.filter_by(user_id=user.id).filter(Notification.read_at.is_(None))
    updated = q.update({'read_at': now}, synchronize_session=False)
    db.session.commit()
    if _is_es(lang):
        speak = f"Marqué {updated} notificaciones como leídas."
    else:
        speak = f"Marked {updated} notifications as read."
    return {'speak': speak, 'redirect_url': url_for('office.notifications')}


def _tool_search_library_documents(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    query = (args.get('query') or '').strip().lower()
    limit = args.get('limit')
    try:
        limit_int = int(limit) if limit is not None else 10
    except Exception:
        limit_int = 10
    limit_int = max(1, min(limit_int, 25))

    docs = LibraryDocument.query.order_by(LibraryDocument.created_at.desc()).limit(200).all()
    if query:
        docs = [d for d in docs if query in ((d.title or '').lower() + ' ' + (d.description or '').lower() + ' ' + (d.original_filename or '').lower())]
    docs = docs[:limit_int]

    if not docs:
        return {'speak': 'No encontré documentos.' if _is_es(lang) else "I couldn't find any documents.", 'redirect_url': url_for('office.library')}

    parts = []
    for d in docs:
        title = d.title or d.original_filename or f"#{d.id}"
        parts.append(f"{d.id}: {title}")

    speak = ('Documentos: ' if _is_es(lang) else 'Documents: ') + '; '.join(parts)
    return {'speak': speak, 'redirect_url': url_for('office.library')}


def _tool_create_library_project(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    name = (args.get('name') or '').strip()
    if not name:
        return {'speak': 'Falta el nombre.' if _is_es(lang) else 'Missing name.'}

    existing = Project.query.filter_by(name=name).first()
    if existing:
        return {'speak': 'Ese proyecto ya existe.' if _is_es(lang) else 'That project already exists.', 'redirect_url': url_for('office.library_projects')}

    project = Project(name=name, active=True)
    db.session.add(project)
    db.session.commit()
    return {'speak': 'Proyecto creado.' if _is_es(lang) else 'Project created.', 'redirect_url': url_for('office.library_projects')}


def _tool_email_library_document(args: Dict[str, Any], user: User, lang: str) -> Dict[str, Any]:
    doc_id = args.get('document_id')
    to_email = (args.get('to_email') or '').strip()
    message = (args.get('message') or '').strip()
    try:
        doc_id_int = int(doc_id)
    except Exception:
        doc_id_int = None

    if not doc_id_int:
        return {'speak': 'Falta el ID del documento.' if _is_es(lang) else 'Missing document id.'}
    if not to_email:
        return {'speak': 'Falta el correo.' if _is_es(lang) else 'Missing recipient email.'}

    doc = LibraryDocument.query.get(doc_id_int)
    if not doc:
        return {'speak': 'No encontré el documento.' if _is_es(lang) else "I couldn't find the document.", 'redirect_url': url_for('office.library')}

    abs_path = get_document_abs_path(doc.stored_filename)
    try:
        with open(abs_path, 'rb') as f:
            data = f.read()
    except Exception:
        return {'speak': 'No pude leer el archivo.' if _is_es(lang) else "I couldn't read the file.", 'redirect_url': url_for('office.view_library_document', id=doc.id)}

    subject = doc.title or doc.original_filename or 'Document'
    text_body = message or ("Adjunto el documento." if _is_es(lang) else 'Attached is the document.')
    html_body = f"<p>{text_body}</p>"
    sender = (
        (current_app.config.get('MAIL_DEFAULT_SENDER') or '').strip()
        or (user.email or '').strip()
        or 'noreply@example.com'
    )

    send_email_with_attachments_sync(
        subject=subject,
        sender=sender,
        recipients=[to_email],
        text_body=text_body,
        html_body=html_body,
        attachments=[(doc.original_filename or 'document', doc.content_type or 'application/octet-stream', data)],
    )

    return {
        'speak': 'Correo enviado.' if _is_es(lang) else 'Email sent.',
        'redirect_url': url_for('office.view_library_document', id=doc.id),
    }


def _openai_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    api_key = current_app.config.get('OPENAI_API_KEY')
    timeout = int(current_app.config.get('OPENAI_TIMEOUT') or 15)
    if not api_key:
        raise RuntimeError('Missing OPENAI_API_KEY')

    res = requests.post(
        'https://api.openai.com/v1/chat/completions',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        data=json.dumps(payload),
        timeout=timeout,
    )
    res.raise_for_status()
    return res.json()


def run_assistant(text: str, lang: str, user: User) -> Dict[str, Any]:
    model = (current_app.config.get('OPENAI_MODEL') or 'gpt-4o-mini').strip()

    name_for_balance = None
    asked_lower = (text or '').lower()
    if any(k in asked_lower for k in ['balance', 'saldo']):
        name_for_balance = _extract_customer_name_for_balance(text, lang)
        if name_for_balance:
            return _tool_customer_balance({'customer_name': name_for_balance}, lang)

    tools = [
        {
            'type': 'function',
            'function': {
                'name': 'meetings_today',
                'description': 'List today meetings from the agenda.',
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'customer_balance',
                'description': 'Get the open balance for a customer by name.',
                'parameters': {
                    'type': 'object',
                    'properties': {'customer_name': {'type': 'string'}},
                    'required': ['customer_name'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'overdue_invoices',
                'description': 'Check how many overdue invoices exist.',
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'payments_to_collect_this_week',
                'description': 'Compute how much should be collected this week (sum of balances for invoices due in next 7 days).',
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'open_section',
                'description': 'Navigate the user to a section of the app (agenda, invoices, notifications, dashboard).',
                'parameters': {
                    'type': 'object',
                    'properties': {'section': {'type': 'string'}},
                    'required': ['section'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'create_meeting',
                'description': 'Create a meeting in the agenda. Prefer ISO 8601 for start_at/end_at.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'title': {'type': 'string'},
                        'start_at': {'type': 'string'},
                        'end_at': {'type': 'string'},
                        'location': {'type': 'string'},
                        'notes': {'type': 'string'},
                        'reminder_minutes': {'type': 'integer'},
                    },
                    'required': ['title', 'start_at'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'list_customers',
                'description': 'List customers.',
                'parameters': {
                    'type': 'object',
                    'properties': {'limit': {'type': 'integer'}},
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'create_customer',
                'description': 'Create a new customer (client).',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'name': {'type': 'string'},
                        'email': {'type': 'string'},
                        'phone': {'type': 'string'},
                        'address': {'type': 'string'},
                        'tax_id': {'type': 'string'},
                        'credit_limit': {'type': 'number'},
                    },
                    'required': ['name'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'create_invoice',
                'description': 'Create an invoice for a customer (simple single-line invoice).',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'customer_name': {'type': 'string'},
                        'amount': {'type': 'number'},
                        'description': {'type': 'string'},
                        'date': {'type': 'string'},
                        'due_date': {'type': 'string'},
                        'tax': {'type': 'number'},
                        'terms': {'type': 'string'},
                        'notes': {'type': 'string'},
                    },
                    'required': ['customer_name', 'amount'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'create_bill',
                'description': 'Create a bill for a vendor (simple single-line bill).',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'vendor_name': {'type': 'string'},
                        'amount': {'type': 'number'},
                        'description': {'type': 'string'},
                        'date': {'type': 'string'},
                        'due_date': {'type': 'string'},
                        'tax': {'type': 'number'},
                        'terms': {'type': 'string'},
                        'notes': {'type': 'string'},
                    },
                    'required': ['vendor_name', 'amount'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'email_invoice',
                'description': 'Email an invoice PDF to a recipient.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'number_or_id': {'type': 'string'},
                        'to_email': {'type': 'string'},
                        'to_name': {'type': 'string'},
                        'message': {'type': 'string'},
                        'confirm': {'type': 'boolean'},
                        'save_contact': {'type': 'boolean'},
                    },
                    'required': ['number_or_id'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'email_quote',
                'description': 'Email a quote PDF to a recipient.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'number_or_id': {'type': 'string'},
                        'to_email': {'type': 'string'},
                        'to_name': {'type': 'string'},
                        'message': {'type': 'string'},
                        'confirm': {'type': 'boolean'},
                        'save_contact': {'type': 'boolean'},
                    },
                    'required': ['number_or_id'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'email_purchase_order',
                'description': 'Email a purchase order (PO) PDF to a recipient.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'number_or_id': {'type': 'string'},
                        'to_email': {'type': 'string'},
                        'to_name': {'type': 'string'},
                        'message': {'type': 'string'},
                        'confirm': {'type': 'boolean'},
                        'save_contact': {'type': 'boolean'},
                    },
                    'required': ['number_or_id'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'record_payment',
                'description': 'Record a customer payment (not tied to a specific invoice).',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'customer_name': {'type': 'string'},
                        'amount': {'type': 'number'},
                        'date': {'type': 'string'},
                        'payment_method': {'type': 'string'},
                        'reference': {'type': 'string'},
                        'notes': {'type': 'string'},
                    },
                    'required': ['customer_name', 'amount'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'list_open_invoices',
                'description': 'List open invoices (balance > 0).',
                'parameters': {
                    'type': 'object',
                    'properties': {'limit': {'type': 'integer'}},
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'invoice_summary',
                'description': 'Get a summary for an invoice by number or id.',
                'parameters': {
                    'type': 'object',
                    'properties': {'number_or_id': {'type': 'string'}},
                    'required': ['number_or_id'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'list_quotes',
                'description': 'List recent quotes.',
                'parameters': {
                    'type': 'object',
                    'properties': {'limit': {'type': 'integer'}},
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'create_quote',
                'description': 'Create a quote for a customer (simple single-line quote).',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'customer_name': {'type': 'string'},
                        'amount': {'type': 'number'},
                        'description': {'type': 'string'},
                        'date': {'type': 'string'},
                        'valid_until': {'type': 'string'},
                        'tax': {'type': 'number'},
                        'status': {'type': 'string'},
                        'terms': {'type': 'string'},
                        'notes': {'type': 'string'},
                    },
                    'required': ['customer_name', 'amount'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'create_purchase_order',
                'description': 'Create a purchase order (simple single-line PO).',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'po_type': {'type': 'string', 'description': 'vendor or customer'},
                        'vendor_name': {'type': 'string'},
                        'customer_name': {'type': 'string'},
                        'amount': {'type': 'number'},
                        'description': {'type': 'string'},
                        'date': {'type': 'string'},
                        'tax': {'type': 'number'},
                        'status': {'type': 'string'},
                        'terms': {'type': 'string'},
                        'notes': {'type': 'string'},
                    },
                    'required': ['po_type', 'amount'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'edit_quote',
                'description': 'Edit a quote by number or id (header fields and optionally simple amount/description).',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'number_or_id': {'type': 'string'},
                        'customer_name': {'type': 'string'},
                        'amount': {'type': 'number'},
                        'description': {'type': 'string'},
                        'date': {'type': 'string'},
                        'valid_until': {'type': 'string'},
                        'tax': {'type': 'number'},
                        'status': {'type': 'string'},
                        'terms': {'type': 'string'},
                        'notes': {'type': 'string'},
                    },
                    'required': ['number_or_id'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'delete_quote',
                'description': 'Delete a quote by number or id. Requires confirm=true to execute.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'number_or_id': {'type': 'string'},
                        'confirm': {'type': 'boolean'},
                    },
                    'required': ['number_or_id'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'convert_quote_to_invoice',
                'description': 'Convert a quote to an invoice. Requires confirm=true to execute.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'number_or_id': {'type': 'string'},
                        'confirm': {'type': 'boolean'},
                    },
                    'required': ['number_or_id'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'list_bills',
                'description': 'List recent bills (accounts payable).',
                'parameters': {
                    'type': 'object',
                    'properties': {'limit': {'type': 'integer'}},
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'list_unread_notifications',
                'description': 'List unread notifications for the current user.',
                'parameters': {
                    'type': 'object',
                    'properties': {'limit': {'type': 'integer'}},
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'mark_all_notifications_read',
                'description': 'Mark all unread notifications as read for the current user.',
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False},
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'search_library_documents',
                'description': 'Search documents in the Document Library by title/description/filename.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'query': {'type': 'string'},
                        'limit': {'type': 'integer'},
                    },
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'create_library_project',
                'description': 'Create a Document Library project.',
                'parameters': {
                    'type': 'object',
                    'properties': {'name': {'type': 'string'}},
                    'required': ['name'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'email_library_document',
                'description': 'Email a Document Library document as an attachment.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'document_id': {'type': 'integer'},
                        'to_email': {'type': 'string'},
                        'message': {'type': 'string'},
                    },
                    'required': ['document_id', 'to_email'],
                    'additionalProperties': False,
                },
            },
        },
    ]

    system = (
        'You are an assistant inside an accounting, operations, and document library web application. '
        'You have access to business data in this app for the current logged-in user. '
        'You must be concise. '
        'When the user asks about customers, invoices, quotes, bills, meetings, notifications, or documents, '
        'use the provided tools instead of refusing. '
        'You can also create customers when asked. '
        'You can also create invoices when asked. '
        'You can also email invoices and record payments when asked. '
        'You can also create, edit, delete, convert, and email quotes when asked (confirm before delete/convert/email). '
        'If the user mentions a person name while asking for balance, treat it as a CUSTOMER name (not a system user). '
        'It is allowed to provide customer balances and invoice totals from this app. '
        'Only say you cannot access something when there is no suitable tool. '
        'Respond in Spanish when lang starts with es, otherwise English.'
    )

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': text},
        ],
        'tools': tools,
        'tool_choice': 'auto',
        'temperature': 0.2,
        'max_tokens': int(current_app.config.get('OPENAI_MAX_TOKENS') or 250),
    }

    data = _openai_request(payload)
    choice = (data.get('choices') or [{}])[0]
    message = choice.get('message') or {}

    tool_calls = message.get('tool_calls') or []
    if tool_calls:
        call = tool_calls[0]
        fn = (call.get('function') or {})
        name = fn.get('name')
        args_raw = fn.get('arguments') or '{}'
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
        except Exception:
            args = {}

        if name == 'meetings_today':
            return _tool_meetings_today(lang)
        if name == 'overdue_invoices':
            return _tool_overdue_invoices(lang)
        if name == 'payments_to_collect_this_week':
            return _tool_payments_to_collect_this_week(lang)
        if name == 'open_section':
            return _tool_open_section(args.get('section') or '', lang)
        if name == 'create_meeting':
            return _tool_create_meeting(args, user, lang)
        if name == 'list_customers':
            return _tool_list_customers(args, lang)
        if name == 'create_customer':
            return _tool_create_customer(args, lang)
        if name == 'create_invoice':
            return _tool_create_invoice(args, lang)
        if name == 'create_bill':
            return _tool_create_bill(args, lang)
        if name == 'email_invoice':
            return _tool_email_invoice(args, user, lang)
        if name == 'email_purchase_order':
            return _tool_email_purchase_order(args, user, lang)
        if name == 'record_payment':
            return _tool_record_payment(args, lang)
        if name == 'customer_balance':
            return _tool_customer_balance(args, lang)
        if name == 'list_open_invoices':
            return _tool_list_open_invoices(args, lang)
        if name == 'invoice_summary':
            return _tool_invoice_summary(args, lang)
        if name == 'list_quotes':
            return _tool_list_quotes(args, lang)
        if name == 'create_quote':
            return _tool_create_quote(args, lang)
        if name == 'create_purchase_order':
            return _tool_create_purchase_order(args, lang)
        if name == 'edit_quote':
            return _tool_edit_quote(args, lang)
        if name == 'delete_quote':
            return _tool_delete_quote(args, lang)
        if name == 'convert_quote_to_invoice':
            return _tool_convert_quote_to_invoice(args, lang)
        if name == 'email_quote':
            return _tool_email_quote(args, user, lang)
        if name == 'list_bills':
            return _tool_list_bills(args, lang)
        if name == 'list_unread_notifications':
            return _tool_list_unread_notifications(args, user, lang)
        if name == 'mark_all_notifications_read':
            return _tool_mark_all_notifications_read(args, user, lang)
        if name == 'search_library_documents':
            return _tool_search_library_documents(args, lang)
        if name == 'create_library_project':
            return _tool_create_library_project(args, lang)
        if name == 'email_library_document':
            return _tool_email_library_document(args, user, lang)

        return {'speak': 'Acción no soportada.' if _is_es(lang) else 'Unsupported action.'}

    content = (message.get('content') or '').strip()
    if not content:
        return {'speak': 'No entendí.' if _is_es(lang) else "I didn't understand."}

    refusal_markers = [
        'no puedo acceder',
        'no puedo acceder a',
        'no tengo acceso',
        'i cannot access',
        "i can't access",
        'cannot access',
        'can\'t access',
    ]
    lowered = content.lower()
    if any(m in lowered for m in refusal_markers):
        asked = (text or '').lower()
        if any(k in asked for k in ['balance', 'saldo']):
            name = _extract_customer_name_for_balance(text, lang)
            if name:
                return _tool_customer_balance({'customer_name': name}, lang)

    return {'speak': content}
