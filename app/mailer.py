"""Send the digest through Gmail SMTP with an app password.

The recipient comes only from the DIGEST_TO environment variable. The LLM
never sees this module and has no tool that sends mail.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage


def send_digest(subject: str, html_body: str, text_body: str) -> str:
    sender = os.environ["GMAIL_ADDRESS"].strip()
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "").strip()
    recipient = os.environ.get("DIGEST_TO", sender).strip()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"AI PM Digest <{sender}>"
    msg["To"] = recipient
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP_SSL(
        "smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30
    ) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    return recipient
