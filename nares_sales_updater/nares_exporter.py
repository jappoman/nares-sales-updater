"""Esecuzione delle 4 estrazioni NARES (menu -> servizi -> export).

Nota: i selettori e gli URL del portale NARES vanno calibrati sul portale reale
(la prima esecuzione live mostrera eventuali differenze). Tutto e configurabile
in config.json -> nares.
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

from . import config as cfg
from .browser import CdpBrowser, NaresSession, SESSION_CACHE_NAME
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
          const setValue = (element, nextValue) => {{
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
            setter.call(element, nextValue);
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

    def _click_confirm(self) -> str:
        return self._js("""
        (() => {
          const btn = [...document.querySelectorAll("button,input[type=submit],a")]
            .find(b => /conferma/i.test((b.innerText || b.value || "")));
          if (!btn) return "CONFIRM_BUTTON_NOT_FOUND";
          btn.click();
          return "OK";
        })()
        """)

    def _click_menu_export(self) -> str:
        return self._js("""
        (() => {
          const link = [...document.querySelectorAll("a[onclick]")]
            .find(a => (a.innerText || "").trim() === "Export" &&
              /Servizi\\s*>\\s*Export/.test(a.getAttribute("onclick") || ""));
          if (!link) return "EXPORT_MENU_NOT_FOUND";
          link.click();
          return "OK";
        })()
        """)

    def _date_selectors_for(self, export_key: str) -> tuple[str, str]:
        selectors = {
            "orders": ("#dataordineda_input", "#dataordinea_input"),
            "ordersByDate": ("#dataconsegnada_input", "#dataconsegnaa_input"),
            "preventivi": ("#datapreventivoda_input", "#datapreventivoa_input"),
            "ingressi": ("#dataDal", "#dataAl"),
        }
        try:
            return selectors[export_key]
        except KeyError as exc:
            raise ConfigError(f"Export '{export_key}': selettori data non configurati") from exc

    # -- flusso --------------------------------------------------------------
    def open_export_page(self) -> None:
        self.browser.navigate(self.nares["main_url"], wait_seconds=8)
        result = self._click_menu_export()
        if result != "OK":
            raise ConfigError(f"Apertura Export: {result}")
        self.browser.wait(6)

    def _wait_download(self, expected_names: list[str], wait_max: float = 180.0) -> Path:
        start = time.time()
        seen = set()
        while time.time() - start < wait_max:
            files = {
                p for p in self.download_dir.iterdir()
                if p.is_file() and not p.name.endswith((".crdownload", ".tmp"))
            }
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

        result = self._click_confirm()
        if result != "OK":
            raise ConfigError(f"Export '{export_key}': {result}")
        self.browser.wait(6)

        date_from_selector, date_to_selector = self._date_selectors_for(export_key)
        if export_key == "ingressi" and "anno_from" in date_range:
            for selector, value in (
                (date_from_selector, str(date_range["anno_from"])),
                (date_to_selector, str(date_range["anno_to"])),
            ):
                result = self._set_input(selector, value)
                if result != "OK":
                    raise ConfigError(f"Export '{export_key}': {result} (campo anno {selector})")
        elif "date_from" in date_range and "date_to" in date_range:
            date_from: date = date_range["date_from"]
            date_to: date = date_range["date_to"]
            fmt = "%d/%m/%Y"
            for selector, value in (
                (date_from_selector, date_from.strftime(fmt)),
                (date_to_selector, date_to.strftime(fmt)),
            ):
                result = self._set_input(selector, value)
                if result != "OK":
                    raise ConfigError(f"Export '{export_key}': {result} (campo data {selector})")
        elif "anno_from" in date_range:
            for selector, value in (
                (date_from_selector, f"01/01/{date_range['anno_from']}"),
                (date_to_selector, f"31/12/{date_range['anno_to']}"),
            ):
                result = self._set_input(selector, value)
                if result != "OK":
                    raise ConfigError(f"Export '{export_key}': {result} (campo anno/data {selector})")

        if export_key == "ordersByDate":
            result = self._js(f"""
            (() => {{
              const box = document.querySelector({self.selectors["export_societa"]!r});
              if (!box) return "INPUT_NOT_FOUND";
              if (!box.checked) box.click();
              return "OK";
            }})()
            """)
            if result != "OK":
                raise ConfigError(f"Export 'ordersByDate': {result} (campo societa)")

        result = self._click_export()
        if result != "OK":
            raise ConfigError(f"Export '{export_key}': {result}")
        # Il rapportino annuale contiene tutti i negozi e richiede piu tempo
        # degli altri export lato NARES.
        wait_max = 420.0 if export_key == "ingressi" else 180.0
        return self._wait_download([spec["download_name"]], wait_max=wait_max)


def download_all_exports(config: dict, credentials: dict, date_ranges: dict,
                         download_dir: Path, logger=print) -> dict[str, Path]:
    """Scarica i 4 file. Ritorna {export_key: path}."""
    session = NaresSession(config, credentials, cfg.APP_DIR / SESSION_CACHE_NAME)
    cookies = session.login()
    browser = CdpBrowser(detect_edge_path_safe(config))
    try:
        browser.start(download_dir=download_dir)
        browser.set_cookies(cookies)
        page = ExportPage(browser, config, download_dir, logger)
        results = {}
        for key, spec in config["exports"].items():
            # Dopo ogni download NARES resta sul form specifico dell'export:
            # rientriamo dal menu JSF per poter scegliere il successivo.
            page.open_export_page()
            results[key] = page.run_export(key, spec, date_ranges[key])
        return results
    finally:
        browser.close()


def detect_edge_path_safe(config: dict):
    from .browser import detect_edge_path

    return detect_edge_path(config)
