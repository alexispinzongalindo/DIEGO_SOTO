from datetime import datetime, timedelta
import os

from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user

from app import db
from app.models import Meeting, Notification, Invoice
from app.office import bp
from app.office.forms import MeetingForm
from app.office.ai_assistant import run_assistant


@bp.app_context_processor
def inject_office_nav():
    if not current_user.is_authenticated:
        return {}
    unread_count = Notification.query.filter_by(user_id=current_user.id).filter(Notification.read_at.is_(None)).count()
    return {
        'unread_notifications': unread_count,
    }


def _ensure_notifications():
    if not current_user.is_authenticated:
        return

    now = datetime.utcnow()

    upcoming = Meeting.query.filter(Meeting.start_at >= now, Meeting.start_at <= now + timedelta(days=7)).order_by(Meeting.start_at.asc()).all()
    for meeting in upcoming:
        if meeting.reminder_minutes is None:
            continue
        remind_at = meeting.start_at - timedelta(minutes=int(meeting.reminder_minutes))
        if remind_at <= now <= meeting.start_at:
            exists = Notification.query.filter_by(
                user_id=current_user.id,
                ref_type='meeting',
                ref_id=meeting.id,
                type='meeting_reminder',
            ).first()
            if exists:
                continue
            notif = Notification(
                user_id=current_user.id,
                type='meeting_reminder',
                title='Meeting Reminder',
                body=f"{meeting.title} at {meeting.start_at.strftime('%Y-%m-%d %H:%M')}",
                link=url_for('office.meetings'),
                severity='info',
                ref_type='meeting',
                ref_id=meeting.id,
            )
            db.session.add(notif)

    overdue_invoices = Invoice.query.filter(Invoice.due_date.isnot(None)).all()
    today = now.date()
    for inv in overdue_invoices:
        if inv.balance <= 0.01:
            continue
        if inv.due_date and inv.due_date < today:
            exists = Notification.query.filter_by(
                user_id=current_user.id,
                ref_type='invoice',
                ref_id=inv.id,
                type='invoice_overdue',
            ).first()
            if exists:
                continue
            notif = Notification(
                user_id=current_user.id,
                type='invoice_overdue',
                title='Invoice Overdue',
                body=f"Invoice {inv.number} is overdue. Balance ${float(inv.balance or 0):,.2f}",
                link=url_for('ar.view_invoice', id=inv.id),
                severity='warning',
                ref_type='invoice',
                ref_id=inv.id,
            )
            db.session.add(notif)

    db.session.commit()


@bp.before_app_request
def before_app_request():
    try:
        _ensure_notifications()
    except Exception:
        db.session.rollback()


@bp.route('/meetings')
@login_required
def meetings():
    now = datetime.utcnow()
    meeting_list = Meeting.query.order_by(Meeting.start_at.asc()).all()
    return render_template('office/meetings.html', title='Agenda', meetings=meeting_list, now=now)


@bp.route('/agenda/owner-questions/create', methods=['POST'])
@login_required
def create_owner_questions_agenda_item():
    title = 'Owner Questions: Email/SMS AI Assistant'
    existing = Meeting.query.filter_by(title=title).order_by(Meeting.start_at.desc()).first()
    if existing:
        flash('Owner questions already added to Agenda.', 'info')
        return redirect(url_for('office.meetings'))

    start = datetime.utcnow().replace(second=0, microsecond=0) + timedelta(hours=1)
    notes = (
        'Questions to confirm before enabling the assistant to read/respond to Email + TXT:\n'
        '\n'
        '1) Email provider: Gmail/Google Workspace, Outlook/M365, or IMAP?\n'
        '2) Which inbox/address should the system monitor?\n'
        '3) SMS/TXT provider: Twilio? Do we already have an account/number?\n'
        '4) Auto-reply policy: Draft-only (recommended) or Auto-send for low-risk messages?\n'
        '5) Languages: English only or English + Spanish?\n'
        '6) Allowed senders / client allowlist?\n'
        '7) Confirmation required for sending collections/payment-related messages?\n'
    )

    meeting = Meeting(
        title=title,
        start_at=start,
        end_at=start + timedelta(minutes=30),
        location='Office',
        notes=notes,
        reminder_minutes=60,
        created_by_id=current_user.id,
    )
    db.session.add(meeting)
    db.session.commit()
    flash('Owner questions added to Agenda.', 'success')
    return redirect(url_for('office.meetings'))


@bp.route('/meeting/create', methods=['GET', 'POST'])
@login_required
def create_meeting():
    form = MeetingForm()
    if request.method == 'GET':
        start = datetime.utcnow().replace(second=0, microsecond=0) + timedelta(hours=1)
        form.start_at.data = start
        form.end_at.data = start + timedelta(hours=1)
        if form.reminder_minutes.data is None:
            form.reminder_minutes.data = 60

    if form.validate_on_submit():
        meeting = Meeting(
            title=form.title.data,
            start_at=form.start_at.data,
            end_at=form.end_at.data,
            location=form.location.data,
            notes=form.notes.data,
            reminder_minutes=form.reminder_minutes.data if form.reminder_minutes.data is not None else 60,
            created_by_id=current_user.id,
        )
        db.session.add(meeting)
        db.session.commit()
        flash('Meeting created.', 'success')
        return redirect(url_for('office.meetings'))

    return render_template('office/create_meeting.html', title='Create Meeting', form=form)


@bp.route('/notifications')
@login_required
def notifications():
    notif_list = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(200).all()
    return render_template('office/notifications.html', title='Notifications', notifications=notif_list)


@bp.route('/notification/<int:id>/read', methods=['POST'])
@login_required
def mark_notification_read(id):
    notif = Notification.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    notif.read_at = datetime.utcnow()
    db.session.commit()
    return redirect(request.referrer or url_for('office.notifications'))


@bp.route('/assistant/status', methods=['GET'])
def assistant_status():
    try:
        routes_mtime = os.path.getmtime(__file__)
    except Exception:
        routes_mtime = None
    return jsonify({
        'openai_enabled': bool(current_app.config.get('OPENAI_API_KEY')),
        'pid': os.getpid(),
        'routes_mtime': routes_mtime,
    })


@bp.route('/assistant/command', methods=['POST'])
@login_required
def assistant_command():
    payload = request.get_json(silent=True) or {}
    raw_text = (payload.get('text') or '').strip()
    text = raw_text.lower()
    lang = (payload.get('lang') or '').strip().lower()
    is_es = lang.startswith('es')
    pid = os.getpid()

    if current_app.config.get('OPENAI_API_KEY'):
        try:
            return jsonify(run_assistant(raw_text, lang, current_user))
        except Exception as e:
            db.session.rollback()
            msg = str(e) or 'unknown error'
            msg = msg.replace('\n', ' ').strip()
            if len(msg) > 180:
                msg = msg[:180] + '...'
            dbg = f" (pid={pid})"
            return jsonify({'speak': (f'Error de OpenAI: {msg}{dbg}' if is_es else f'OpenAI error: {msg}{dbg}')})

    now = datetime.utcnow()

    if any(k in text for k in ['agenda', 'meetings', 'meeting today', 'today meetings']) or (is_es and any(k in text for k in ['reuniones', 'reunión', 'reunion', 'reuniones hoy', 'reuniones de hoy', 'reunion hoy', 'reunión hoy'])):
        start = datetime(now.year, now.month, now.day)
        end = start + timedelta(days=1)
        meetings = Meeting.query.filter(Meeting.start_at >= start, Meeting.start_at < end).order_by(Meeting.start_at.asc()).all()
        if not meetings:
            return jsonify({'speak': 'No tienes reuniones hoy.' if is_es else 'You have no meetings today.'})
        parts = []
        for m in meetings[:5]:
            parts.append(f"{m.title} at {m.start_at.strftime('%H:%M')}")
        if is_es:
            speak = 'Hoy tienes: ' + '; '.join(parts)
        else:
            speak = 'Today you have: ' + '; '.join(parts)
        return jsonify({'speak': speak, 'redirect_url': url_for('office.meetings')})

    if any(k in text for k in ['overdue', 'past due', 'late invoices']) or (is_es and any(k in text for k in ['facturas vencidas', 'facturas atrasadas', 'facturas en mora', 'facturas tarde'])):
        today = now.date()
        invoices = Invoice.query.filter(Invoice.due_date.isnot(None)).all()
        overdue = [inv for inv in invoices if inv.due_date and inv.due_date < today and inv.balance > 0.01]
        if not overdue:
            return jsonify({'speak': 'No tienes facturas vencidas.' if is_es else 'You have no overdue invoices.'})
        speak = f"Tienes {len(overdue)} facturas vencidas." if is_es else f"You have {len(overdue)} overdue invoices."
        return jsonify({'speak': speak, 'redirect_url': url_for('ar.invoices')})

    if 'open invoices' in text or 'go to invoices' in text or 'invoices' == text or (is_es and (text == 'facturas' or 'abrir facturas' in text or 'ir a facturas' in text)):
        return jsonify({'speak': 'Abriendo facturas.' if is_es else 'Opening invoices.', 'redirect_url': url_for('ar.invoices')})

    if 'open agenda' in text or 'go to agenda' in text or (is_es and ('abrir agenda' in text or 'ir a agenda' in text or text == 'agenda')):
        return jsonify({'speak': 'Abriendo agenda.' if is_es else 'Opening agenda.', 'redirect_url': url_for('office.meetings')})

    if 'notifications' in text or (is_es and 'notificaciones' in text):
        return jsonify({'speak': 'Abriendo notificaciones.' if is_es else 'Opening notifications.', 'redirect_url': url_for('office.notifications')})

    if 'dashboard' in text or (is_es and any(k in text for k in ['tablero', 'panel', 'inicio'])):
        return jsonify({'speak': 'Abriendo tablero.' if is_es else 'Opening dashboard.', 'redirect_url': url_for('main.dashboard')})

    openai_enabled = bool(current_app.config.get('OPENAI_API_KEY'))
    dbg = f" (openai={int(openai_enabled)}, pid={pid})"
    return jsonify({'speak': ("No entendí. Prueba: 'reuniones hoy' o 'facturas vencidas'." if is_es else "I didn't understand. Try: 'today's meetings' or 'overdue invoices'.") + dbg})
