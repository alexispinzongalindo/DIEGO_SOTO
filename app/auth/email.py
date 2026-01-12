from flask import render_template, current_app
from app import mail
from threading import Thread
from flask_mail import Message
import base64
import requests
import socket
import smtplib
import ssl


def _mail_config_summary(app):
    cfg = app.config
    return {
        'MAIL_SERVER': cfg.get('MAIL_SERVER'),
        'MAIL_PORT': cfg.get('MAIL_PORT'),
        'MAIL_USE_TLS': cfg.get('MAIL_USE_TLS'),
        'MAIL_USE_SSL': cfg.get('MAIL_USE_SSL'),
        'MAIL_USERNAME': cfg.get('MAIL_USERNAME'),
        'MAIL_DEFAULT_SENDER': cfg.get('MAIL_DEFAULT_SENDER'),
    }


def _decode_smtp_bytes(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            return value.decode('utf-8', errors='replace')
        except Exception:
            return repr(value)
    return str(value)


def _format_mail_send_error(app, exc):
    cfg = _mail_config_summary(app)

    if isinstance(exc, (socket.gaierror,)):
        return f"SMTP host could not be resolved (MAIL_SERVER={cfg.get('MAIL_SERVER')})."

    if isinstance(exc, OSError) and getattr(exc, 'errno', None) == -2:
        return f"SMTP host could not be resolved (MAIL_SERVER={cfg.get('MAIL_SERVER')})."

    if isinstance(exc, smtplib.SMTPAuthenticationError):
        details = _decode_smtp_bytes(getattr(exc, 'smtp_error', None))
        return (
            "SMTP authentication failed (check MAIL_USERNAME/MAIL_PASSWORD). "
            f"Details: {details}. Config: {cfg}"
        )

    if isinstance(exc, (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, smtplib.SMTPHeloError)):
        return (
            "Could not connect to SMTP server. "
            "Check MAIL_SERVER/MAIL_PORT and whether MAIL_USE_TLS or MAIL_USE_SSL is required. "
            f"Config: {cfg}"
        )

    if isinstance(exc, ssl.SSLError):
        return (
            "SSL/TLS error when connecting to SMTP. "
            "This often means a TLS/SSL mismatch (e.g. MAIL_USE_SSL on port 587 or MAIL_USE_TLS on port 465). "
            f"Config: {cfg}. Original error: {exc}"
        )

    args = getattr(exc, 'args', None) or ()
    if len(args) >= 2 and args[0] == -1 and isinstance(args[1], (bytes, bytearray)):
        details = _decode_smtp_bytes(args[1])
        return (
            "Low-level SSL/TLS failure while sending email. "
            "Check MAIL_PORT and MAIL_USE_TLS/MAIL_USE_SSL. "
            f"Details: {details}. Config: {cfg}"
        )

    return f"Email send failed. Config: {cfg}. Original error: {exc}"

def send_async_email(app, msg):
    with app.app_context():
        try:
            socket.setdefaulttimeout(int(app.config.get('MAIL_TIMEOUT') or 10))
            mail.send(msg)
        except Exception as e:
            app.logger.exception('Email send failed')
            app.logger.error(_format_mail_send_error(app, e))


def send_email_sync(subject, sender, recipients, text_body, html_body):
    msg = Message(subject, sender=sender, recipients=recipients)
    msg.body = text_body
    msg.html = html_body
    if not (current_app.config.get('MAIL_SERVER') or '').strip():
        raise RuntimeError(
            'Email is not configured. Set RESEND_API_KEY+RESEND_FROM, or SENDGRID_API_KEY+SENDGRID_FROM, '
            'or MAIL_SERVER/MAIL_PORT (SMTP).'
        )

    try:
        socket.setdefaulttimeout(int(current_app.config.get('MAIL_TIMEOUT') or 10))
        mail.send(msg)
    except Exception as e:
        current_app.logger.exception('Email send failed')
        raise RuntimeError(_format_mail_send_error(current_app, e)) from e

def send_email(subject, sender, recipients, text_body, html_body):
    msg = Message(subject, sender=sender, recipients=recipients)
    msg.body = text_body
    msg.html = html_body
    Thread(target=send_async_email, args=(current_app._get_current_object(), msg)).start()


def send_email_with_attachments(subject, sender, recipients, text_body, html_body, attachments):
    Thread(
        target=_send_email_with_attachments_safe,
        args=(
            current_app._get_current_object(),
            subject,
            sender,
            recipients,
            text_body,
            html_body,
            attachments,
        ),
    ).start()


def _send_email_with_attachments_safe(app, subject, sender, recipients, text_body, html_body, attachments):
    with app.app_context():
        try:
            send_email_with_attachments_sync(
                subject=subject,
                sender=sender,
                recipients=recipients,
                text_body=text_body,
                html_body=html_body,
                attachments=attachments,
            )
        except Exception as e:
            app.logger.exception('Email send failed')
            app.logger.error(str(e))


def send_email_with_attachments_sync(subject, sender, recipients, text_body, html_body, attachments):
    resend_key = (current_app.config.get('RESEND_API_KEY') or '').strip()
    resend_from = (current_app.config.get('RESEND_FROM') or '').strip()
    if resend_key and resend_from:
        try:
            return _send_via_resend(
                api_key=resend_key,
                subject=subject,
                sender=sender,
                recipients=recipients,
                text_body=text_body,
                html_body=html_body,
                attachments=attachments,
            )
        except Exception:
            current_app.logger.exception('Resend send failed; falling back to next provider')

    sendgrid_key = (current_app.config.get('SENDGRID_API_KEY') or '').strip()
    sendgrid_from = (current_app.config.get('SENDGRID_FROM') or '').strip()
    if sendgrid_key and sendgrid_from:
        try:
            return _send_via_sendgrid(
                api_key=sendgrid_key,
                subject=subject,
                sender=sender,
                recipients=recipients,
                text_body=text_body,
                html_body=html_body,
                attachments=attachments,
            )
        except Exception:
            current_app.logger.exception('SendGrid send failed; falling back to SMTP')

    if resend_key and not resend_from:
        current_app.logger.error('RESEND_API_KEY is set but RESEND_FROM is not set; skipping Resend')
    if sendgrid_key and not sendgrid_from:
        current_app.logger.error('SENDGRID_API_KEY is set but SENDGRID_FROM is not set; skipping SendGrid')

    msg = Message(subject, sender=sender, recipients=recipients)
    msg.body = text_body
    msg.html = html_body

    for attachment in attachments or []:
        filename, content_type, data = attachment
        msg.attach(filename, content_type, data)

    if not (current_app.config.get('MAIL_SERVER') or '').strip():
        raise RuntimeError(
            'Email is not configured. Set RESEND_API_KEY+RESEND_FROM, or SENDGRID_API_KEY+SENDGRID_FROM, '
            'or MAIL_SERVER/MAIL_PORT (SMTP).'
        )

    try:
        socket.setdefaulttimeout(int(current_app.config.get('MAIL_TIMEOUT') or 10))
        mail.send(msg)
    except Exception as e:
        current_app.logger.exception('Email send failed')
        raise RuntimeError(_format_mail_send_error(current_app, e)) from e


def _send_via_sendgrid(api_key, subject, sender, recipients, text_body, html_body, attachments):
    from_email = (current_app.config.get('SENDGRID_FROM') or '').strip()
    if not from_email:
        raise RuntimeError('SendGrid is enabled but SENDGRID_FROM is not set.')

    payload = {
        'personalizations': [{'to': [{'email': r} for r in (recipients or [])]}],
        'from': {'email': from_email},
        'subject': subject,
        'content': [
            {'type': 'text/plain', 'value': text_body or ''},
            {'type': 'text/html', 'value': html_body or ''},
        ],
    }

    if attachments:
        sg_attachments = []
        for filename, content_type, data in attachments:
            if isinstance(data, str):
                data = data.encode('utf-8')
            sg_attachments.append(
                {
                    'content': base64.b64encode(data).decode('ascii'),
                    'type': content_type,
                    'filename': filename,
                    'disposition': 'attachment',
                }
            )
        payload['attachments'] = sg_attachments

    timeout = int(current_app.config.get('SENDGRID_TIMEOUT') or 10)
    try:
        resp = requests.post(
            'https://api.sendgrid.com/v3/mail/send',
            json=payload,
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=timeout,
        )
    except Exception as e:
        raise RuntimeError(f'SendGrid send failed: {e}') from e
    if resp.status_code >= 400:
        raise RuntimeError(f'SendGrid send failed: {resp.status_code} {resp.text}')


def _send_via_resend(api_key, subject, sender, recipients, text_body, html_body, attachments):
    from_email = (current_app.config.get('RESEND_FROM') or '').strip()
    if not from_email:
        raise RuntimeError('Resend is enabled but RESEND_FROM is not set.')

    to_emails = [r for r in (recipients or []) if r]
    if not to_emails:
        raise RuntimeError('No recipients provided.')

    payload = {
        'from': from_email,
        'to': to_emails,
        'subject': subject,
    }
    if html_body:
        payload['html'] = html_body
    if text_body:
        payload['text'] = text_body

    if attachments:
        rs_attachments = []
        for filename, content_type, data in attachments:
            if isinstance(data, str):
                data = data.encode('utf-8')
            rs_attachments.append(
                {
                    'filename': filename,
                    'content': base64.b64encode(data).decode('ascii'),
                    'content_type': content_type,
                }
            )
        payload['attachments'] = rs_attachments

    timeout = int(current_app.config.get('RESEND_TIMEOUT') or 10)
    try:
        resp = requests.post(
            'https://api.resend.com/emails',
            json=payload,
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=timeout,
        )
    except Exception as e:
        raise RuntimeError(f'Resend send failed: {e}') from e
    if resp.status_code >= 400:
        raise RuntimeError(f'Resend send failed: {resp.status_code} {resp.text}')

def send_password_reset_email(user):
    token = user.get_reset_password_token()
    send_email(
        'Reset Your Password',
        sender=current_app.config['ADMINS'][0],
        recipients=[user.email],
        text_body=render_template('email/reset_password.txt', user=user, token=token),
        html_body=render_template('email/reset_password.html', user=user, token=token)
    )

def send_welcome_email(user):
    send_email(
        'Welcome to Diego Soto & Associates',
        sender=current_app.config['ADMINS'][0],
        recipients=[user.email],
        text_body=render_template('email/welcome.txt', user=user),
        html_body=render_template('email/welcome.html', user=user)
    )
