from flask import render_template, current_app
from app import mail
from threading import Thread
from flask_mail import Message
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
    msg = Message(subject, sender=sender, recipients=recipients)
    msg.body = text_body
    msg.html = html_body

    for attachment in attachments or []:
        filename, content_type, data = attachment
        msg.attach(filename, content_type, data)

    Thread(target=send_async_email, args=(current_app._get_current_object(), msg)).start()


def send_email_with_attachments_sync(subject, sender, recipients, text_body, html_body, attachments):
    msg = Message(subject, sender=sender, recipients=recipients)
    msg.body = text_body
    msg.html = html_body

    for attachment in attachments or []:
        filename, content_type, data = attachment
        msg.attach(filename, content_type, data)

    try:
        socket.setdefaulttimeout(int(current_app.config.get('MAIL_TIMEOUT') or 10))
        mail.send(msg)
    except Exception as e:
        current_app.logger.exception('Email send failed')
        raise RuntimeError(_format_mail_send_error(current_app, e)) from e

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
