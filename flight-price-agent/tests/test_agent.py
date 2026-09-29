import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from price_agent.agent import run_checks
from price_agent.config import ConfigError, load_config
from price_agent.history import History
from price_agent.mailer import SmtpSettings, build_message
from price_agent.models import Quote, Route
from price_agent.providers.base import PriceProvider, ProviderError, cheapest_per_trip
from price_agent.providers.demo import DemoProvider
from price_agent.providers.travelpayouts import TravelpayoutsProvider
from price_agent.report import build_subject, render_html, render_text
from price_agent.whatsapp import (
    WhatsAppError, WhatsAppSettings, build_whatsapp_messages, build_whatsapp_text, send_whatsapp,
)

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

    def test_beach_config(self):
        cfg = load_config(ROOT / "config.toml")
        self.assertEqual(cfg.departure_dates(TODAY), [date(2027, 1, d) for d in (2, 3, 4)])
        self.assertEqual(cfg.departure_dates(date(2027, 1, 3)), [date(2027, 1, 3), date(2027, 1, 4)])
        self.assertEqual(cfg.stay_range, [12, 13, 14])
        self.assertIn(Route("BUE", "FLN"), cfg.routes)

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
        cfg.stay_nights_min = cfg.stay_nights_max = 7
        reports = run_checks(cfg, DemoProvider(cfg, seed="x"), History(":memory:"), TODAY)
        html = render_html(reports, TODAY, cfg)
        text = render_text(reports, TODAY, cfg)
        subject = build_subject(reports, TODAY)
        self.assertIn("EZE ✈ MIA", html)
        self.assertIn("== AEP-GRU ==", text)
        self.assertIn("29/09/2026", subject)


class StayRangeTests(unittest.TestCase):
    def test_compares_same_trip_and_renders_matrix(self):
        cfg = example_config()
        cfg.fixed_dates = [date(2027, 1, d) for d in (2, 3, 4)]
        cfg.stay_nights_min, cfg.stay_nights_max = 12, 14
        hist = History(":memory:")
        run_checks(cfg, DemoProvider(cfg, seed="a"), hist, TODAY - timedelta(days=1))
        reports = run_checks(cfg, DemoProvider(cfg, seed="b"), hist, TODAY)
        r = reports[0]
        self.assertEqual(len(r.result.quotes), 9)
        self.assertEqual(len(r.previous), 9)
        q = r.result.quotes[0]
        prev = r.previous[(q.departure, q.return_date)]
        self.assertAlmostEqual(r.change_pct(q), (q.price - prev) / prev * 100)
        html = render_html(reports, TODAY, cfg)
        self.assertIn("Ida \\ Noches", html)
        self.assertIn("viajes más baratos", html)
        self.assertIn("(12n)", render_text(reports, TODAY, cfg))


class ProviderTests(unittest.TestCase):
    def test_cheapest_per_trip(self):
        r = Route("EZE", "MIA")
        d = date(2026, 10, 1)
        ret = d + timedelta(days=12)
        out = cheapest_per_trip([
            Quote(r, d, 500, "USD", return_date=ret),
            Quote(r, d, 420, "USD", return_date=ret),
            Quote(r, d, 450, "USD", return_date=ret + timedelta(days=1)),
        ])
        self.assertEqual([q.price for q in out], [420, 450])

    def test_travelpayouts_round_trip_stay_range(self):
        cfg = example_config()
        cfg.stay_nights_min, cfg.stay_nights_max = 12, 14
        item = lambda dep, ret, price: {
            "departure_at": f"{dep}T10:00:00-03:00", "return_at": f"{ret}T10:00:00-03:00",
            "price": price, "airline": "G3", "transfers": 1,
        }
        payload = {"success": True, "data": [
            item("2027-01-02", "2027-01-14", 700),   # 12 noches
            item("2027-01-02", "2027-01-14", 650),   # mismo viaje, más barato
            item("2027-01-03", "2027-01-17", 600),   # 14 noches
            item("2027-01-03", "2027-01-20", 300),   # 17 noches: fuera de rango
            item("2027-01-05", "2027-01-18", 200),   # fecha de ida no pedida
        ]}
        with mock.patch.dict("os.environ", {"TRAVELPAYOUTS_TOKEN": "t"}), mock.patch(
            "price_agent.providers.travelpayouts.get_json", return_value=payload
        ) as gj, mock.patch("price_agent.providers.travelpayouts.time.sleep"):
            quotes = TravelpayoutsProvider(cfg).fetch(
                Route("EZE", "FLN"), [date(2027, 1, d) for d in (2, 3, 4)]
            )
        self.assertEqual(gj.call_count, 1)
        params = gj.call_args[0][1]
        self.assertEqual((params["departure_at"], params["return_at"], params["one_way"]),
                         ("2027-01", "2027-01", "false"))
        self.assertEqual([(q.departure.day, q.return_date.day, q.price) for q in quotes],
                         [(2, 14, 650), (3, 17, 600)])

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
        ) as gj, mock.patch("price_agent.providers.travelpayouts.time.sleep"):
            p = TravelpayoutsProvider(cfg)
            quotes = p.fetch(Route("EZE", "MIA"), [date(2026, 10, 1), date(2026, 10, 2)])
        self.assertEqual(gj.call_count, 1)
        self.assertEqual(len(quotes), 1)
        self.assertEqual((quotes[0].price, quotes[0].airline, quotes[0].stops), (480, "AR", 0))
        self.assertTrue(quotes[0].link.startswith("https://www.aviasales.com/search/"))


class TwiceADayTests(unittest.TestCase):
    def test_second_run_same_day_compares_with_midnight_run(self):
        cfg = example_config()
        hist = History(":memory:")
        midnight = datetime(2026, 9, 29, 0, 0)
        run_checks(cfg, FixedProvider(cfg, lambda r, d: 500), hist, TODAY, run_at=midnight)
        reports = run_checks(cfg, FixedProvider(cfg, lambda r, d: 450), hist, TODAY,
                             run_at=midnight.replace(hour=10))
        r = reports[0]
        self.assertAlmostEqual(r.change_pct(r.result.quotes[0]), -10.0)
        self.assertEqual(r.previous_cheapest, 500)


class WhatsAppTests(unittest.TestCase):
    def _reports(self):
        cfg = example_config()
        cfg.fixed_dates = [date(2027, 1, 2)]
        cfg.stay_nights_min, cfg.stay_nights_max = 12, 14
        return run_checks(cfg, DemoProvider(cfg, seed="w"), History(":memory:"), TODAY)

    def test_text(self):
        text = build_whatsapp_text(self._reports(), TODAY)
        self.assertIn("*Vuelos a Brasil · 29/09 00:00*", text)
        self.assertIn("🏆 *Top", text)
        self.assertIn("📍 *Mejor precio por destino*", text)
        self.assertIn("(12n)", text)

    def test_full_report_split_in_messages(self):
        cfg = load_config(ROOT / "config.toml")
        cfg.history_db = ":memory:"
        hist = History(":memory:")
        run_checks(cfg, DemoProvider(cfg, seed="a"), hist, TODAY, run_at=datetime(2026, 9, 29, 0))
        now = datetime(2026, 9, 29, 10)
        reports = run_checks(cfg, DemoProvider(cfg, seed="b"), hist, TODAY, run_at=now)
        reports[-1].result.quotes = []  # un destino sin vuelos
        msgs = build_whatsapp_messages(reports, now, cfg)
        text = "\n".join(msgs)
        self.assertGreater(len(msgs), 1)
        self.assertTrue(all(len(m) <= 1000 for m in msgs))
        self.assertIn("Ida 2, 3 o 4 de enero · vuelta a las 12–14 noches", text)
        self.assertIn("10. ", text)
        self.assertIn("• Florianópolis:", text)
        self.assertIn("❌ *Sin vuelos encontrados:* Jericoacoara", text)
        self.assertRegex(text, "[🔻🔺]\\d+%")  # variación contra la corrida anterior

    def test_send_multiple_messages(self):
        s = WhatsAppSettings("callmebot", "+5491112345678", apikey="k")
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b"Message queued."
        with mock.patch("urllib.request.urlopen", return_value=resp) as uo, \
                mock.patch("price_agent.whatsapp.time.sleep") as sl:
            send_whatsapp(s, ["uno", "dos", "tres"])
        self.assertEqual(uo.call_count, 3)
        self.assertEqual(sl.call_count, 2)

    def test_settings_normalize_phone(self):
        env = {"WHATSAPP_PHONE": "+54 9 11 1234-5678", "CALLMEBOT_APIKEY": "k"}
        with mock.patch.dict("os.environ", env, clear=True):
            s = WhatsAppSettings.from_env()
        self.assertEqual((s.provider, s.phone), ("callmebot", "+5491112345678"))
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(WhatsAppSettings.from_env())
        with mock.patch.dict("os.environ", {"WHATSAPP_PHONE": "+541"}, clear=True):
            with self.assertRaises(WhatsAppError):
                WhatsAppSettings.from_env()

    def test_callmebot_request(self):
        s = WhatsAppSettings("callmebot", "+5491112345678", apikey="k")
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b"Message queued. You will receive it in a few seconds."
        with mock.patch("urllib.request.urlopen", return_value=resp) as uo:
            send_whatsapp(s, "hola ✈️")
        url = uo.call_args[0][0]
        self.assertIn("phone=%2B5491112345678", url)
        self.assertIn("apikey=k", url)
        resp.__enter__.return_value.read.return_value = b"<p>APIKey is invalid. Error</p>"
        with mock.patch("urllib.request.urlopen", return_value=resp):
            with self.assertRaises(WhatsAppError):
                send_whatsapp(s, "hola")


class MailTests(unittest.TestCase):
    def test_message(self):
        s = SmtpSettings("smtp.x", 587, "me@x.com", "pw", "me@x.com", ["a@x.com", "b@x.com"])
        msg = build_message(s, "Asunto", "texto", "<b>html</b>")
        self.assertEqual(msg["To"], "a@x.com, b@x.com")
        self.assertTrue(msg.is_multipart())


if __name__ == "__main__":
    unittest.main()
