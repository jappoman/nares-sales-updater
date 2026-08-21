"""Esecuzione delle 4 estrazioni NARES (menu -> servizi -> export).

Nota: i selettori e gli URL del portale NARES vanno calibrati sul portale reale
(la prima esecuzione live mostrerà eventuali differenze). Tutto è configurabile
in config.json -> nares.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from .browser import CdpBrowser, NaresSession, SESSION_CACHE_NAME
from . import config as cfg
from .config import ConfigError


class ExportPage:
    def __init__(self, browser: CdpBrowser, config: dict, download_dir: Path, logger=print) -> None:
        self.browser = browser
        self.config = config
        self.nares = config["nares"]
        self.selectors = self.nares["selectors"]
        self.download_dir = download_dir
        self.logger = logger
        self.download_dir.mkdir(parents=True, exist_ok=True)

    # -- helper JS ----------------------------------------------------------
    def _js(self, expression: str):
        return self.browser.evaluate(expression)

    def _set_select(self, selector: str, label: str) -> str:
        """Seleziona l'opzione di una <select> in base al testo visibile."""
        return self._js(f"""
        (() => {{
          const sel = document.querySelector({selector!r});
          if (!sel) return "SELECT_NOT_FOUND";
          const options = [...sel.options];
          const wanted = {label.lower()!r};
          const idx = options.findIndex(o => (o.text || o.value || "").toLowerCase().includes(wanted));
          if (idx < 0) return "OPTION_NOT_FOUND:" + options.map(o => o.text).join("|");
          sel.selectedIndex = idx;
          sel.dispatchEvent(new Event("change", {{ bubbles: true }}));
          return "OK";
        }})()
        """)

    def _set_input(self, selector: str, value: str) -> str:
        return self._js(f"""
        (() => {{
          const setValue = (element, value) => {{
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
            setter.call(element, value);
            element.dispatchEvent(new Event("input", {{ bubbles: true }}));
            element.dispatchEvent(new Event("change", {{ bubbles: true }}));
          }};
          const el = document.querySelector({selector!r});
          if (!el) return "INPUT_NOT_FOUND";
          setValue(el, {value!r});
          return "OK";
        }})()
        """)

    def _click_export(self) -> str:
        return self._js(f"""
        (() => {{
          const sel = {self.selectors["export_submit"]!r};
          let btn = document.querySelector(sel);
          if (!btn) btn = [...document.querySelectorAll("input[type=submit], button")]
            .find(b => /export|esporta|scarica/i.test((b.value || b.innerText || "")));
          if (!btn) return "EXPORT_BUTTON_NOT_FOUND";
          btn.click();
          return "OK";
        }})()
        """)

    # -- flusso --------------------------------------------------------------
    def open_export_page(self) -> None:
        export_url = self.nares.get("export_url", self.nares["portal_base"] + "/pages/export.jsf")
        self.browser.navigate(export_url, wait_seconds=5)

    def _wait_download(self, expected_names: list[str], wait_max: float = 180.0) -> Path:
        start = time.time()
        seen = set()
        while time.time() - start < wait_max:
            files = {p for p in self.download_dir.iterdir() if p.is_file() and not p.name.endswith((".crdownload", ".tmp"))}
            for p in files:
                if p.name in expected_names:
                    return p
                if p.name not in seen:
                    seen.add(p.name)
                    self.logger(f"Download in corso: {p.name}")
            time.sleep(2)
        raise ConfigError(
            f"Nessun download completato in {int(wait_max)}s. Attesi: {expected_names}. "
            f"Trovati nella cartella: {sorted(p.name for p in self.download_dir.iterdir())[:10]}"
        )

    def run_export(self, export_key: str, spec: dict, date_range: dict) -> Path:
        label = spec["label"]
        self.logger(f"Estrazione '{export_key}' ({label})...")
        result = self._set_select(self.selectors["export_type_select"], label)
        if result != "OK":
            raise ConfigError(f"Export '{export_key}': {result} (verifica il selettore export_type_select)")
        self.browser.wait(1)

        if "date_from" in date_range:
            date_from: date = date_range["date_from"]
            date_to: date = date_range["date_to"]
            fmt = "%d/%m/%Y"
            for selector, value in (
                (self.selectors["export_date_from"], date_from.strftime(fmt)),
                (self.selectors["export_date_to"], date_to.strftime(fmt)),
            ):
                result = self._set_input(selector, value)
                if result != "OK":
                    raise ConfigError(f"Export '{export_key}': {result} (campo data {selector})")
        elif "anno_from" in date_range:
            for selector, value in (
                (self.selectors["export_anno_from"], str(date_range["anno_from"])),
                (self.selectors["export_anno_to"], str(date_range["anno_to"])),
            ):
                result = self._set_input(selector, value)
                if result != "OK":
                    raise ConfigError(f"Export '{export_key}': {result} (campo anno {selector})")

        if export_key == "ordersByDate":
            societa = self.nares.get("societa_orders_by_date", "GENESI RETAIL SRL")
            result = self._set_select(self.selectors["export_societa"], societa)
            if result != "OK":
                raise ConfigError(f"Export 'ordersByDate': {result} (campo società)")

        result = self._click_export()
        if result != "OK":
            raise ConfigError(f"Export '{export_key}': {result}")
        return self._wait_download([spec["download_name"]])


def download_all_exports(config: dict, credentials: dict, date_ranges: dict,
                         download_dir: Path, logger=print) -> dict[str, Path]:
    """Scarica i 4 file. Ritorna {export_key: path}."""
    session = NaresSession(config, credentials, cfg.APP_DIR / SESSION_CACHE_NAME)
    session.login()
    browser = CdpBrowser(detect_edge_path_safe(config))
    try:
        browser.start(download_dir=download_dir)
        page = ExportPage(browser, config, download_dir, logger)
        page.open_export_page()
        results = {}
        for key, spec in config["exports"].items():
            results[key] = page.run_export(key, spec, date_ranges[key])
        return results
    finally:
        browser.close()


def detect_edge_path_safe(config: dict):
    from .browser import detect_edge_path

    return detect_edge_path(config)
