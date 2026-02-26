import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


def _send_email(to: str, subject: str, body: str) -> None:
    """Send an email via SMTP or print to console (dev)."""
    settings = get_settings()

    if settings.email_sender_backend == "console":
        print(f"[EMAIL-CONSOLE] to={to} subject={subject}")
        print(f"  body: {body[:200]}")
        return

    if settings.email_sender_backend != "smtp":
        raise ValueError(f"Unsupported email sender backend: {settings.email_sender_backend}")

    if not settings.smtp_host or not settings.smtp_from_email:
        raise ValueError("SMTP host/from email not configured")

    msg = EmailMessage()
    msg["Subject"] = subject
    if settings.smtp_from_alias:
        msg["From"] = f"{settings.smtp_from_alias} <{settings.smtp_from_email}>"
    else:
        msg["From"] = settings.smtp_from_email
    msg["To"] = to
    msg.set_content(body)

    if settings.smtp_use_ssl:
        # Aliyun DirectMail uses port 465 with implicit SSL
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)


def send_verification_code(email: str, code: str, purpose: str) -> None:
    settings = get_settings()
    subject = "Knoweia - 邮箱验证码"
    body = (
        f"您好，\n\n"
        f"您的验证码是：{code}\n"
        f"有效期 {settings.email_code_expire_seconds // 60} 分钟。\n\n"
        f"如果您没有请求此验证码，请忽略本邮件。\n\n"
        f"— Knoweia"
    )
    _send_email(email, subject, body)


def send_waitlist_confirmation(email: str) -> None:
    subject = "Knoweia - 感谢加入等待列表"
    body = (
        f"您好，\n\n"
        f"感谢您对 Knoweia 的关注！\n"
        f"您的邮箱 {email} 已加入等待列表。\n"
        f"我们会在产品开放注册时第一时间通知您。\n\n"
        f"— Knoweia"
    )
    _send_email(email, subject, body)
