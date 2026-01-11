from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

import requests
from dateutil import parser
from flask import current_app, url_for

from app import db
from app.auth.email import send_email_with_attachments_sync
from app.models import Bill, Customer, Invoice, LibraryDocument, Meeting, Notification, Project, Quote, User
from app.office.library_storage import get_document_abs_path


def _utc_now() -> datetime:
    return datetime.utcnow()


def _is_es(lang: str) -> bool:
    return (lang or '').strip().lower().startswith('es')


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


def _tool_customer_balance(args: Dict[str, Any], lang: str) -> Dict[str, Any]:
    name = (args.get('customer_name') or '').strip()
    if not name:
        return {'speak': 'Falta el nombre del cliente.' if _is_es(lang) else 'Missing customer name.'}

    customer = (
        Customer.query.filter(Customer.name.ilike(f"%{name}%"))
        .order_by(Customer.name.asc())
        .first()
    )
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
        if name == 'customer_balance':
            return _tool_customer_balance(args, lang)
        if name == 'list_open_invoices':
            return _tool_list_open_invoices(args, lang)
        if name == 'invoice_summary':
            return _tool_invoice_summary(args, lang)
        if name == 'list_quotes':
            return _tool_list_quotes(args, lang)
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
