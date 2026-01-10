from flask import render_template, current_app
from app import mail
from threading import Thread
from flask_mail import Message
import socket

def send_async_email(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
        except socket.gaierror:
            app.logger.exception('Email send failed (DNS resolution error)')
        except OSError as e:
            if getattr(e, 'errno', None) == -2:
                app.logger.exception('Email send failed (DNS resolution error)')
            else:
                app.logger.exception('Email send failed')
        except Exception:
            app.logger.exception('Email send failed')


def send_email_sync(subject, sender, recipients, text_body, html_body):
    msg = Message(subject, sender=sender, recipients=recipients)
    msg.body = text_body
    msg.html = html_body
    try:
        mail.send(msg)
    except socket.gaierror as e:
        current_app.logger.exception('Email send failed (DNS resolution error)')
        host = current_app.config.get('MAIL_SERVER')
        raise RuntimeError(f"SMTP host could not be resolved (MAIL_SERVER={host}). Original error: {e}")
    except OSError as e:
        if getattr(e, 'errno', None) == -2:
            current_app.logger.exception('Email send failed (DNS resolution error)')
            host = current_app.config.get('MAIL_SERVER')
            raise RuntimeError(f"SMTP host could not be resolved (MAIL_SERVER={host}). Original error: {e}")
        current_app.logger.exception('Email send failed')
        raise
    except Exception:
        current_app.logger.exception('Email send failed')
        raise

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
        mail.send(msg)
    except socket.gaierror as e:
        current_app.logger.exception('Email send failed (DNS resolution error)')
        host = current_app.config.get('MAIL_SERVER')
        raise RuntimeError(f"SMTP host could not be resolved (MAIL_SERVER={host}). Original error: {e}")
    except OSError as e:
        if getattr(e, 'errno', None) == -2:
            current_app.logger.exception('Email send failed (DNS resolution error)')
            host = current_app.config.get('MAIL_SERVER')
            raise RuntimeError(f"SMTP host could not be resolved (MAIL_SERVER={host}). Original error: {e}")
        current_app.logger.exception('Email send failed')
        raise
    except Exception:
        current_app.logger.exception('Email send failed')
        raise

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
