from datetime import datetime, timedelta
import os

from flask import render_template, redirect, url_for, flash, request, jsonify, current_app, send_file, session
from flask_login import login_required, current_user

from app import db
from app.auth.email import send_email_with_attachments_sync
from app.models import AppSetting, Meeting, Notification, Invoice, User, Project, LibraryDocument
from app.office import bp
from app.office.forms import MeetingForm, ProjectForm, LibraryDocumentForm, EmailLibraryDocumentForm, DeleteForm, AdminSettingsForm
from app.office.ai_assistant import run_assistant
from app.office.library_storage import save_uploaded_file, get_document_abs_path, delete_document_file
from sqlalchemy import inspect, text


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


def _can_edit_document(doc: LibraryDocument) -> bool:
    if not current_user.is_authenticated:
        return False
    if getattr(current_user, 'is_admin', False):
        return True
    return doc.owner_id == current_user.id


@bp.route('/library')
@login_required
def library():
    owner_id = request.args.get('owner_id', type=int)
    category = (request.args.get('category') or '').strip().lower() or None
    project_id = request.args.get('project_id', type=int)

    q = LibraryDocument.query
    if owner_id:
        q = q.filter(LibraryDocument.owner_id == owner_id)
    if category in ('project', 'personal'):
        q = q.filter(LibraryDocument.category == category)
    if project_id:
        q = q.filter(LibraryDocument.project_id == project_id)

    documents = q.order_by(LibraryDocument.created_at.desc()).limit(200).all()

    owners = User.query.order_by(User.username.asc()).all()
    projects = Project.query.filter_by(active=True).order_by(Project.name.asc()).all()

    return render_template(
        'office/library.html',
        title='Document Library',
        documents=documents,
        owners=owners,
        projects=projects,
        selected_owner_id=owner_id,
        selected_category=category,
        selected_project_id=project_id,
    )


@bp.route('/library/projects')
@login_required
def library_projects():
    projects = Project.query.order_by(Project.name.asc()).all()
    return render_template('office/library_projects.html', title='Projects', projects=projects)


@bp.route('/library/project/create', methods=['GET', 'POST'])
@login_required
def create_library_project():
    if not getattr(current_user, 'is_admin', False):
        flash('Admin access required.', 'warning')
        return redirect(url_for('office.library_projects'))

    form = ProjectForm()
    if form.validate_on_submit():
        name = (form.name.data or '').strip()
        exists = Project.query.filter(Project.name.ilike(name)).first()
        if exists:
            flash('Project already exists.', 'warning')
            return render_template('office/create_library_project.html', title='Create Project', form=form)
        project = Project(name=name, active=True)
        db.session.add(project)
        db.session.commit()
        flash('Project created.', 'success')
        return redirect(url_for('office.library_projects'))

    return render_template('office/create_library_project.html', title='Create Project', form=form)


@bp.route('/library/upload', methods=['GET', 'POST'])
@login_required
def upload_library_document():
    owners = User.query.order_by(User.username.asc()).all()
    projects = Project.query.filter_by(active=True).order_by(Project.name.asc()).all()

    form = LibraryDocumentForm()
    form.owner_id.choices = [(u.id, u.username) for u in owners]
    form.project_id.choices = [(0, '-- None --')] + [(p.id, p.name) for p in projects]

    if request.method == 'GET':
        form.owner_id.data = current_user.id
        form.category.data = 'personal'

    if form.validate_on_submit():
        file = request.files.get('file')
        if not file or not file.filename:
            flash('Please choose a file.', 'danger')
            return render_template('office/upload_library_document.html', title='Upload Document', form=form)

        try:
            saved = save_uploaded_file(file)
        except Exception as e:
            flash(str(e) or 'Unable to save file.', 'danger')
            return render_template('office/upload_library_document.html', title='Upload Document', form=form)

        project_id = form.project_id.data or 0
        if project_id == 0:
            project_id = None
        if form.category.data == 'project' and not project_id:
            flash('Select a project for Project category.', 'danger')
            delete_document_file(saved.get('stored_filename'))
            return render_template('office/upload_library_document.html', title='Upload Document', form=form)

        doc = LibraryDocument(
            owner_id=form.owner_id.data,
            category=form.category.data,
            project_id=project_id,
            title=form.title.data,
            description=form.description.data,
            original_filename=saved.get('original_filename'),
            stored_filename=saved.get('stored_filename'),
            content_type=saved.get('content_type'),
            size_bytes=saved.get('size_bytes'),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(doc)
        db.session.commit()
        flash('Document uploaded.', 'success')
        return redirect(url_for('office.view_library_document', id=doc.id))

    return render_template('office/upload_library_document.html', title='Upload Document', form=form)


@bp.route('/library/document/<int:id>')
@login_required
def view_library_document(id):
    doc = LibraryDocument.query.get_or_404(id)
    delete_form = DeleteForm()
    return render_template(
        'office/view_library_document.html',
        title=f'Document {doc.title}',
        doc=doc,
        can_edit=_can_edit_document(doc),
        delete_form=delete_form,
    )


@bp.route('/library/document/<int:id>/download')
@login_required
def download_library_document(id):
    doc = LibraryDocument.query.get_or_404(id)
    abs_path = get_document_abs_path(doc.stored_filename)
    if not os.path.exists(abs_path):
        flash('File not found on server.', 'danger')
        return redirect(url_for('office.view_library_document', id=doc.id))
    return send_file(abs_path, as_attachment=True, download_name=(doc.original_filename or 'document'))


@bp.route('/library/document/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_library_document(id):
    doc = LibraryDocument.query.get_or_404(id)
    if not _can_edit_document(doc):
        flash('You do not have permission to edit this document.', 'warning')
        return redirect(url_for('office.view_library_document', id=doc.id))

    owners = User.query.order_by(User.username.asc()).all()
    projects = Project.query.filter_by(active=True).order_by(Project.name.asc()).all()

    form = LibraryDocumentForm(obj=doc)
    form.submit.label.text = 'Save Changes'
    form.owner_id.choices = [(u.id, u.username) for u in owners]
    form.project_id.choices = [(0, '-- None --')] + [(p.id, p.name) for p in projects]

    if request.method == 'GET':
        form.owner_id.data = doc.owner_id
        form.category.data = doc.category
        form.project_id.data = doc.project_id or 0

    if form.validate_on_submit():
        project_id = form.project_id.data or 0
        if project_id == 0:
            project_id = None
        if form.category.data == 'project' and not project_id:
            flash('Select a project for Project category.', 'danger')
            return render_template('office/edit_library_document.html', title=f'Edit {doc.title}', form=form, doc=doc)

        doc.owner_id = form.owner_id.data
        doc.category = form.category.data
        doc.project_id = project_id
        doc.title = form.title.data
        doc.description = form.description.data
        doc.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Document updated.', 'success')
        return redirect(url_for('office.view_library_document', id=doc.id))

    return render_template('office/edit_library_document.html', title=f'Edit {doc.title}', form=form, doc=doc)


@bp.route('/library/document/<int:id>/delete', methods=['POST'])
@login_required
def delete_library_document(id):
    doc = LibraryDocument.query.get_or_404(id)
    if not _can_edit_document(doc):
        flash('You do not have permission to delete this document.', 'warning')
        return redirect(url_for('office.view_library_document', id=doc.id))

    form = DeleteForm()
    if not form.validate_on_submit():
        flash('Unable to delete document.', 'danger')
        return redirect(url_for('office.view_library_document', id=doc.id))

    delete_document_file(doc.stored_filename)
    db.session.delete(doc)
    db.session.commit()
    flash('Document deleted.', 'success')
    return redirect(url_for('office.library'))


@bp.route('/library/document/<int:id>/email', methods=['GET', 'POST'])
@login_required
def email_library_document(id):
    doc = LibraryDocument.query.get_or_404(id)
    form = EmailLibraryDocumentForm()

    if form.validate_on_submit():
        abs_path = get_document_abs_path(doc.stored_filename)
        if not os.path.exists(abs_path):
            flash('File not found on server.', 'danger')
            return redirect(url_for('office.view_library_document', id=doc.id))

        try:
            with open(abs_path, 'rb') as f:
                data = f.read()
        except Exception:
            flash('Unable to read file for email.', 'danger')
            return redirect(url_for('office.view_library_document', id=doc.id))

        subject = f"Document: {doc.title}"
        sender = current_app.config.get('MAIL_DEFAULT_SENDER') or current_app.config.get('ADMINS')[0]
        recipients = [form.to_email.data]
        msg = (form.message.data or '').strip()
        text_body = (msg + "\n\n") if msg else ''
        text_body += f"Attached: {doc.original_filename or doc.title}"

        try:
            send_email_with_attachments_sync(
                subject=subject,
                sender=sender,
                recipients=recipients,
                text_body=text_body,
                html_body=f"<p>{text_body}</p>",
                attachments=[(doc.original_filename or 'document', doc.content_type or 'application/octet-stream', data)],
            )
        except Exception as e:
            flash(str(e) or 'Email send failed.', 'danger')
            return render_template('office/email_library_document.html', title=f'Email {doc.title}', form=form, doc=doc)

        flash('Email sent.', 'success')
        return redirect(url_for('office.view_library_document', id=doc.id))

    return render_template('office/email_library_document.html', title=f'Email {doc.title}', form=form, doc=doc)


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


@bp.route('/instructions')
@login_required
def instructions():
    return render_template('office/instructions.html', title='Instructions')


@bp.route('/voice-commands')
@login_required
def voice_commands():
    return render_template('office/voice_commands.html', title='Voice Commands')


def _get_app_setting(key: str) -> str:
    try:
        if not inspect(db.engine).has_table('app_setting'):
            return ''
        row = AppSetting.query.filter_by(key=key).first()
        return (row.value or '').strip() if row else ''
    except Exception:
        db.session.rollback()
        return ''


def _set_app_setting(key: str, value: str):
    try:
        if not inspect(db.engine).has_table('app_setting'):
            return True, ''
        row = AppSetting.query.filter_by(key=key).first()
        if row is None:
            row = AppSetting(key=key)
            db.session.add(row)
        row.value = (value or '').strip()
        row.updated_at = datetime.utcnow()
        db.session.commit()
        return True, ''
    except Exception as e:
        db.session.rollback()
        try:
            msg = (str(e) or '').strip().lower()
            is_trunc = (
                'stringdatarighttruncation' in msg
                or 'value too long for type character varying(200)' in msg
                or 'character varying(200)' in msg
            )
            if is_trunc and db.engine.dialect.name == 'postgresql':
                db.session.execute(text('ALTER TABLE app_setting ALTER COLUMN value TYPE TEXT'))
                db.session.commit()

                row = AppSetting.query.filter_by(key=key).first()
                if row is None:
                    row = AppSetting(key=key)
                    db.session.add(row)
                row.value = (value or '').strip()
                row.updated_at = datetime.utcnow()
                db.session.commit()
                return True, ''
        except Exception:
            db.session.rollback()
        msg = (str(e) or '').strip()
        if msg:
            return False, f"Unable to save settings. {msg}"
        return False, 'Unable to save settings. Database update failed.'


@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if not getattr(current_user, 'is_admin', False):
        flash('Admin access required.', 'warning')
        return redirect(url_for('office.meetings'))

    form = AdminSettingsForm()

    if request.method == 'GET':
        current_val = _get_app_setting('show_marketing_landing').lower()
        enabled = current_val in ('1', 'true', 't', 'yes', 'y', 'on')
        form.show_marketing_landing.data = 'on' if enabled else 'off'

        form.company_name.data = _get_app_setting('company_name')
        form.company_address.data = _get_app_setting('company_address')
        form.company_phone.data = _get_app_setting('company_phone')
        form.company_phone_1.data = _get_app_setting('company_phone_1')
        form.company_phone_2.data = _get_app_setting('company_phone_2')
        form.company_phone_3.data = _get_app_setting('company_phone_3')
        form.company_fax.data = _get_app_setting('company_fax')
        form.company_email.data = _get_app_setting('company_email')
        form.company_email_1.data = _get_app_setting('company_email_1')
        form.company_email_2.data = _get_app_setting('company_email_2')
        form.company_email_3.data = _get_app_setting('company_email_3')
        form.company_logo_path.data = _get_app_setting('company_logo_path')
        form.invoice_important_note.data = _get_app_setting('invoice_important_note')
        form.quote_important_note.data = _get_app_setting('quote_important_note')

    if form.validate_on_submit():
        sel = (form.show_marketing_landing.data or 'off').strip().lower()
        ok, err = _set_app_setting('show_marketing_landing', 'on' if sel == 'on' else 'off')
        if not ok:
            flash(err, 'danger')
            return render_template('office/settings.html', title='Settings', form=form)

        for k, v in [
            ('company_name', form.company_name.data or ''),
            ('company_address', form.company_address.data or ''),
            ('company_phone', form.company_phone.data or ''),
            ('company_phone_1', form.company_phone_1.data or ''),
            ('company_phone_2', form.company_phone_2.data or ''),
            ('company_phone_3', form.company_phone_3.data or ''),
            ('company_fax', form.company_fax.data or ''),
            ('company_email', form.company_email.data or ''),
            ('company_email_1', form.company_email_1.data or ''),
            ('company_email_2', form.company_email_2.data or ''),
            ('company_email_3', form.company_email_3.data or ''),
            ('company_logo_path', form.company_logo_path.data or ''),
            ('invoice_important_note', form.invoice_important_note.data or ''),
            ('quote_important_note', form.quote_important_note.data or ''),
        ]:
            ok, err = _set_app_setting(k, v)
            if not ok:
                flash(err, 'danger')
                return render_template('office/settings.html', title='Settings', form=form)
        flash('Settings saved.', 'success')
        return redirect(url_for('office.settings'))

    return render_template('office/settings.html', title='Settings', form=form)


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

    if not lang:
        stored_lang = (session.get('assistant_lang') or '').strip().lower()
        lang = stored_lang

    if not lang and raw_text:
        lowered = (raw_text or '').strip().lower()
        if lowered in ('en', 'english', 'inglés', 'ingles'):
            lang = 'en'
        elif lowered in ('es', 'spanish', 'español', 'espanol'):
            lang = 'es'

    if not lang:
        return jsonify({'speak': 'Choose language: English or Español.'})

    session['assistant_lang'] = lang
    is_es = lang.startswith('es')

    greeted_key = 'assistant_greeted'
    should_greet = not bool(session.get(greeted_key))
    if should_greet:
        session[greeted_key] = True

    if should_greet and not raw_text:
        return jsonify({'speak': ('Hola. ¿En qué te puedo ayudar hoy?' if is_es else 'Hi. How can I help you today?')})
    pid = os.getpid()

    if current_app.config.get('OPENAI_API_KEY'):
        try:
            result = run_assistant(raw_text, lang, current_user)
            if should_greet and isinstance(result, dict) and (result.get('speak') or '').strip():
                prefix = ('Hola. ' if is_es else 'Hi. ')
                result['speak'] = prefix + (result.get('speak') or '')
            return jsonify(result)
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
