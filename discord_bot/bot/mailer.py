"""Email notifications over stdlib smtplib — zero dependency.

Used to tell an operator about updates, restarts, or anything worth an out-of-
band ping (e.g. a web-admin login link). Sending is done in a worker thread so
a slow SMTP server never blocks the event loop. Can also be called standalone
from shell scripts: ``python -m bot.mailer "subject" "body"``.
"""

from __future__ import annotations

import asyncio
import smtplib
import sys
from email.message import EmailMessage

from .config import MailerConfig


def send_sync(cfg: MailerConfig, subject: str, body: str) -> tuple[bool, str]:
    if not (cfg.enabled and cfg.host and cfg.from_addr and cfg.to_addrs):
        return False, "mailer disabled or misconfigured"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.from_addr
    msg["To"] = ", ".join(cfg.to_addrs)
    msg.set_content(body)
    try:
        if cfg.port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=20)
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=20)
            if cfg.use_tls:
                server.starttls()
        with server:
            if cfg.username:
                server.login(cfg.username, cfg.password)
            server.send_message(msg)
        return True, "sent"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def send(cfg: MailerConfig, subject: str, body: str) -> tuple[bool, str]:
    return await asyncio.to_thread(send_sync, cfg, subject, body)


def _main(argv: list[str]) -> int:
    from .config import Config

    cfg = Config.load().mailer
    subject = argv[0] if argv else "Pi bot notification"
    body = argv[1] if len(argv) > 1 else "(no body)"
    ok, detail = send_sync(cfg, subject, body)
    print(("sent" if ok else "failed") + f": {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
