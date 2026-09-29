import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from price_agent.config import load_config
from price_agent.models import Route
from price_agent.providers import googleflights as gf

ROOT = Path(__file__).resolve().parents[1]
DEP, RET = date(2027, 1, 2), date(2027, 1, 14)
ROUTE = Route("BUE", "FLN")

# Etiquetas reales de Google Flights (capturadas desde GitHub Actions).
LABELS = [
    "From 596 US dollars round trip total.This price does not include overhead bin access. "
    "Nonstop flight with JetSMART. Operated by Jetsmart Airlines S.a.. Leaves Ezeiza International "
    "Airport at 5:30 AM on Saturday, January 2 and arrives at Florianópolis International Airport – "
    "Hercílio Luz at 7:30 AM on Saturday, January 2. Total duration 2 hr.   Select flight",
    "From 1232 US dollars round trip total. 1 stop flight with Aerolineas Argentinas and Gol. Leaves "
    "Aeroparque Internacional Jorge Newbery at 8:40 AM on Sunday, January 3 and arrives at Salvador "
    "International Airport at 4:40 PM on Sunday, January 3. Total duration 8 hr.  Layover (1 of 1) is "
    "a 2 hr 55 min layover at São Paulo. Select flight",
    "From 1,255 US dollars round trip total. 1 stop flight with LATAM. Operated by Latam Airlines "
    "Group. Leaves Aeroparque Internacional Jorge Newbery at 10:30 PM on Sunday, January 3 and "
    "arrives at Salvador International Airport at 10:00 AM on Monday, January 4. Total duration "
    "11 hr 30 min.  Select flight",
    "Some unrelated label",
]


class ParseTests(unittest.TestCase):
    def test_parse_real_labels(self):
        qs = gf.parse_labels(LABELS, ROUTE, DEP, RET, "USD", "u")
        self.assertEqual([q.price for q in qs], [596, 1232, 1255])
        self.assertEqual([q.stops for q in qs], [0, 1, 1])
        self.assertEqual(qs[0].airline, "JetSMART (sale de EZE)")
        self.assertEqual(qs[1].airline, "Aerolineas Argentinas, Gol (sale de AEP)")
        self.assertEqual([q.duration_min for q in qs], [120, 480, 690])
        self.assertTrue(all(q.return_date == RET for q in qs))

    def test_search_url(self):
        url = gf.search_url(ROUTE, DEP, RET, "USD")
        self.assertIn("q=Flights+to+FLN+from+BUE+on+2027-01-02+through+2027-01-14", url)
        self.assertIn("curr=USD", url)
        self.assertIn("oneway", gf.search_url(ROUTE, DEP, None, "USD"))

    def test_config_uses_google_from_bue(self):
        cfg = load_config(ROOT / "config.toml")
        self.assertEqual((cfg.provider, cfg.origins), ("google", ["BUE"]))
        self.assertEqual(len(cfg.routes), 15)


class SkipEmptyRouteTests(unittest.TestCase):
    def test_stops_after_probe_trips_without_results(self):
        cfg = load_config(ROOT / "config.toml")
        p = gf.GoogleFlightsProvider(cfg)
        calls = []

        def fake_search(route, dep, ret):
            calls.append((dep, ret))
            raise gf.ProviderError("no aparecieron resultados")

        p._search = fake_search
        with self.assertRaises(gf.ProviderError):
            p.fetch(ROUTE, [date(2027, 1, d) for d in (2, 3, 4)])
        self.assertEqual(len(calls), 3)  # de 9 combinaciones posibles

    def test_keeps_going_when_some_results(self):
        cfg = load_config(ROOT / "config.toml")
        p = gf.GoogleFlightsProvider(cfg)
        calls = []

        def fake_search(route, dep, ret):
            calls.append(1)
            if len(calls) == 2:
                return gf.parse_labels(LABELS[:1], route, dep, ret, "USD", "u")
            return []

        p._search = fake_search
        quotes = p.fetch(ROUTE, [date(2027, 1, d) for d in (2, 3, 4)])
        self.assertEqual(len(calls), 9)
        self.assertEqual(len(quotes), 1)


CHROMIUM = os.environ.get("CHROMIUM_PATH") or (
    "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else ""
)


@unittest.skipUnless(CHROMIUM or os.environ.get("CI"), "sin Chromium disponible")
class BrowserTests(unittest.TestCase):
    """Corre el proveedor completo contra una página local que imita Google Flights."""

    def test_fetch_with_local_page(self):
        spans = "".join(f'<div aria-label="{l}">x</div>' for l in LABELS[:2])
        html = f"<html><body><div>Cheapest\n from $550</div>{spans}</body></html>"
        tmp = Path(tempfile.mkdtemp()) / "gf.html"
        tmp.write_text(html, encoding="utf-8")

        cfg = load_config(ROOT / "config.toml")
        cfg.stay_nights_min = cfg.stay_nights_max = 12
        env = {"CHROMIUM_PATH": CHROMIUM} if CHROMIUM else {}
        with mock.patch.dict(os.environ, env), mock.patch.object(
            gf, "search_url", return_value=tmp.as_uri()
        ):
            p = gf.GoogleFlightsProvider(cfg)
            p.delay_ms = 0
            try:
                quotes = p.fetch(ROUTE, [DEP])
            finally:
                p.close()
        self.assertEqual(len(quotes), 1)  # uno por viaje (ida + vuelta)
        self.assertEqual(quotes[0].price, 550)  # el de la pestaña "Cheapest"


if __name__ == "__main__":
    unittest.main()
