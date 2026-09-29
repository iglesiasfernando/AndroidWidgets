"""CLI: python -m price_agent --config config.toml [--dry-run] [--provider demo]"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from .agent import run_checks
from .config import ConfigError, load_config
from .history import History
from .mailer import MailError, SmtpSettings, send_mail
from .providers import ProviderError, build_provider
from .report import build_subject, render_html, render_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="price_agent",
        description="Revisa precios de vuelos por día y envía un reporte por mail.",
    )
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--provider", help="Sobrescribe el proveedor del config")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No envía el mail; guarda el reporte en --output",
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
        smtp = None if args.dry_run else SmtpSettings.from_env()
    except (ConfigError, ProviderError, MailError) as e:
        log.error("%s", e)
        return 2

    today = date.today()
    history = History(config.history_db)
    try:
        reports = run_checks(config, provider, history, today)
    finally:
        history.close()

    subject = build_subject(reports, today)
    text = render_text(reports, today, config.top_n)
    html = render_html(reports, today, config.top_n, config.change_threshold_pct)

    if args.dry_run:
        Path(args.output).write_text(html, encoding="utf-8")
        print(subject)
        print(text)
        log.info("Reporte guardado en %s", args.output)
    else:
        try:
            send_mail(smtp, subject, text, html)
        except MailError as e:
            log.error("%s", e)
            return 1
        log.info("Reporte enviado a %s", ", ".join(smtp.recipients))

    if all(r.result.error for r in reports):
        log.error("Todas las rutas fallaron")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
