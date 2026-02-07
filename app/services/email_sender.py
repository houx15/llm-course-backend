import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


def send_verification_code(email: str, code: str, purpose: str) -> None:
    settings = get_settings()
    subject = "Your verification code"
    body = (
        f"Purpose: {purpose}\n"
        f"Verification code: {code}\n"
        f"Expires in: {settings.email_code_expire_seconds} seconds\n"
    )

    if settings.email_sender_backend == "console":
        print(f"[OTP-CONSOLE] to={email} purpose={purpose} code={code}")
        return

    if settings.email_sender_backend != "smtp":
        raise ValueError(f"Unsupported email sender backend: {settings.email_sender_backend}")

    if not settings.smtp_host or not settings.smtp_from_email:
        raise ValueError("SMTP host/from email not configured")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_email
    msg["To"] = email
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)
