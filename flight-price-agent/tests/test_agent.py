import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from price_agent.agent import run_checks
from price_agent.config import ConfigError, load_config
from price_agent.history import History
from price_agent.mailer import SmtpSettings, build_message
from price_agent.models import Quote, Route
from price_agent.providers.base import PriceProvider, ProviderError, cheapest_per_day
from price_agent.providers.demo import DemoProvider
from price_agent.providers.travelpayouts import TravelpayoutsProvider
from price_agent.report import build_subject, render_html, render_text

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 9, 29)


def example_config():
    cfg = load_config(ROOT / "config.example.toml")
    cfg.history_db = ":memory:"
    cfg.days_ahead_start, cfg.days_ahead_end = 1, 14
    return cfg


class FixedProvider(PriceProvider):
    def __init__(self, config, prices, fail=()):
        super().__init__(config)
        self.prices, self.fail = prices, set(fail)

    def fetch(self, route, dates):
        if route.key in self.fail:
            raise ProviderError("boom")
        return [
            Quote(route, d, self.prices(route, d), self.config.currency, airline="XX")
            for d in dates
        ]


class ConfigTests(unittest.TestCase):
    def test_example_config(self):
        cfg = load_config(ROOT / "config.example.toml")
        self.assertEqual(len(cfg.routes), 6)
        self.assertEqual(cfg.alert_for(Route("EZE", "GRU")), 250)
        self.assertEqual(cfg.alert_for(Route("AEP", "GRU")), None)
        self.assertEqual(cfg.alert_for(Route("AEP", "MIA")), 450)
        self.assertEqual(len(cfg.departure_dates(TODAY)), 54)

    def test_invalid_iata(self):
        p = Path(self._tmp()) / "c.toml"
        p.write_text('[airports]\norigins=["EZEE"]\ndestinations=["MIA"]\n')
        with self.assertRaises(ConfigError):
            load_config(p)

    def _tmp(self):
        import tempfile

        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        return d


class AgentTests(unittest.TestCase):
    def test_compares_with_previous_run(self):
        cfg = example_config()
        hist = History(":memory:")
        run_checks(cfg, FixedProvider(cfg, lambda r, d: 500), hist, TODAY - timedelta(days=1))
        reports = run_checks(cfg, FixedProvider(cfg, lambda r, d: 400), hist, TODAY)

        r = reports[0]
        q = r.result.cheapest
        self.assertEqual(q.price, 400)
        self.assertAlmostEqual(r.change_pct(r.result.quotes[5]), -20.0)
        self.assertTrue(r.is_new_low)
        mia = next(x for x in reports if x.route.destination == "MIA")
        self.assertEqual(len(mia.below_alert), 14)

    def test_route_error_does_not_stop_others(self):
        cfg = example_config()
        reports = run_checks(
            cfg, FixedProvider(cfg, lambda r, d: 300, fail={"EZE-MAD"}), History(":memory:"), TODAY
        )
        errs = [r for r in reports if r.result.error]
        self.assertEqual([r.route.key for r in errs], ["EZE-MAD"])

    def test_render(self):
        cfg = example_config()
        cfg.stay_nights = 7
        reports = run_checks(cfg, DemoProvider(cfg, seed="x"), History(":memory:"), TODAY)
        html = render_html(reports, TODAY, cfg.top_n, cfg.change_threshold_pct)
        text = render_text(reports, TODAY, cfg.top_n)
        subject = build_subject(reports, TODAY)
        self.assertIn("EZE ✈ MIA", html)
        self.assertIn("== AEP-GRU ==", text)
        self.assertIn("29/09/2026", subject)


class ProviderTests(unittest.TestCase):
    def test_cheapest_per_day(self):
        r = Route("EZE", "MIA")
        d = date(2026, 10, 1)
        out = cheapest_per_day([Quote(r, d, 500, "USD"), Quote(r, d, 420, "USD")])
        self.assertEqual([q.price for q in out], [420])

    def test_travelpayouts_parsing(self):
        cfg = example_config()
        payload = {
            "success": True,
            "data": [
                {"departure_at": "2026-10-01T10:00:00-03:00", "price": 510, "airline": "AA",
                 "transfers": 1, "duration_to": 600, "link": "/search/EZE0110MIA1"},
                {"departure_at": "2026-10-01T22:00:00-03:00", "price": 480, "airline": "AR",
                 "transfers": 0, "link": "/search/x"},
                {"departure_at": "2026-12-01T10:00:00-03:00", "price": 100, "airline": "ZZ"},
            ],
        }
        with mock.patch.dict("os.environ", {"TRAVELPAYOUTS_TOKEN": "t"}), mock.patch(
            "price_agent.providers.travelpayouts.get_json", return_value=payload
        ) as gj:
            p = TravelpayoutsProvider(cfg)
            quotes = p.fetch(Route("EZE", "MIA"), [date(2026, 10, 1), date(2026, 10, 2)])
        self.assertEqual(gj.call_count, 1)
        self.assertEqual(len(quotes), 1)
        self.assertEqual((quotes[0].price, quotes[0].airline, quotes[0].stops), (480, "AR", 0))
        self.assertTrue(quotes[0].link.startswith("https://www.aviasales.com/search/"))


class MailTests(unittest.TestCase):
    def test_message(self):
        s = SmtpSettings("smtp.x", 587, "me@x.com", "pw", "me@x.com", ["a@x.com", "b@x.com"])
        msg = build_message(s, "Asunto", "texto", "<b>html</b>")
        self.assertEqual(msg["To"], "a@x.com, b@x.com")
        self.assertTrue(msg.is_multipart())


if __name__ == "__main__":
    unittest.main()
