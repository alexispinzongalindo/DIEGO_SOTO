from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

import requests
from dateutil import parser
from flask import current_app, url_for

from app import db
from app.models import Invoice, Meeting, User


def _utc_now() -> datetime:
    return datetime.utcnow()


def _is_es(lang: str) -> bool:
    return (lang or '').strip().lower().startswith('es')


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
    ]

    system = (
        'You are an assistant inside an accounting and agenda web application. '
        'You must be concise. '
        'If the user asks for data that belongs to the app (invoices, payments, meetings), call the appropriate tool. '
        'If you cannot do something, say so briefly. '
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

        return {'speak': 'Acción no soportada.' if _is_es(lang) else 'Unsupported action.'}

    content = (message.get('content') or '').strip()
    if not content:
        return {'speak': 'No entendí.' if _is_es(lang) else "I didn't understand."}

    return {'speak': content}
