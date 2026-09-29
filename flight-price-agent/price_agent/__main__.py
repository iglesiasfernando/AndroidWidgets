"""CLI: python -m price_agent --config config.toml [--dry-run] [--provider demo]"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from .agent import run_checks
from .config import ConfigError, load_config
from .history import History
from .mailer import MailError, SmtpSettings, send_mail
from .providers import ProviderError, build_provider
from .report import build_subject, render_html, render_text
from .whatsapp import WhatsAppError, WhatsAppSettings, build_whatsapp_text, send_whatsapp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="price_agent",
        description="Revisa precios de vuelos y envía un reporte por mail y/o WhatsApp.",
    )
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--provider", help="Sobrescribe el proveedor del config")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No envía nada; guarda el reporte en --output y lo muestra en consola",
    )
    parser.add_argument("--output", default="report.html")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("price_agent")

    try:
        config = load_config(args.config)
        if args.provider:
            config.provider = args.provider
        provider = build_provider(config)
        smtp = wa = None
        if not args.dry_run:
            if os.environ.get("SMTP_HOST") or os.environ.get("MAIL_TO"):
                smtp = SmtpSettings.from_env()
            wa = WhatsAppSettings.from_env()
            if not smtp and not wa:
                raise MailError(
                    "No hay canales configurados: definí SMTP_* / MAIL_TO y/o WHATSAPP_PHONE"
                )
    except (ConfigError, ProviderError, MailError, WhatsAppError) as e:
        log.error("%s", e)
        return 2

    now = datetime.now().replace(microsecond=0)
    today = now.date()
    if not config.departure_dates(today):
        log.warning("Todas las fechas de salida ya pasaron: no hay nada para revisar")
        return 0

    history = History(config.history_db)
    try:
        reports = run_checks(config, provider, history, today, run_at=now)
    finally:
        history.close()
        provider.close()

    subject = build_subject(reports, today)
    text = render_text(reports, today, config)
    html = render_html(reports, today, config)
    wa_text = build_whatsapp_text(reports, today)

    failed = False
    if args.dry_run:
        Path(args.output).write_text(html, encoding="utf-8")
        print(subject)
        print(text)
        print("--- WhatsApp ---")
        print(wa_text)
        log.info("Reporte guardado en %s", args.output)
    if smtp:
        try:
            send_mail(smtp, subject, text, html)
            log.info("Reporte enviado a %s", ", ".join(smtp.recipients))
        except MailError as e:
            log.error("%s", e)
            failed = True
    if wa:
        try:
            send_whatsapp(wa, wa_text)
            log.info("WhatsApp enviado a %s", wa.phone)
        except WhatsAppError as e:
            log.error("%s", e)
            failed = True
    if failed:
        return 1

    if all(r.result.error for r in reports):
        log.error("Todas las rutas fallaron")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
