"""Automazione browser via Edge + Chrome DevTools Protocol (come recupero-dati-barbiere).

Gestisce il login al portale NARES, la cache della sessione (.nares_session.json)
e il download dei 4 file di export. I selettori della pagina sono configurabili
in config.json -> nares.selectors perché il portale può cambiare.
"""
from __future__ import annotations

import itertools
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import websocket

from .config import ConfigError

SESSION_CACHE_NAME = ".nares_session.json"


class CdpBrowser:
    def __init__(self, executable: Path, debug_port: int = 9223) -> None:
        self.executable = executable
        self.debug_port = debug_port
        self.user_data_dir = Path(tempfile.mkdtemp(prefix="edge-nares-"))
        self.process: subprocess.Popen | None = None
        self.websocket = None
        self._message_ids = itertools.count(1)
        self._download_dir: Path | None = None
        self._events: list[dict] = []

    def start(self, download_dir: Path | None = None) -> None:
        self._download_dir = download_dir
        self.process = subprocess.Popen(
            [
                str(self.executable),
                f"--remote-debugging-port={self.debug_port}",
                "--remote-allow-origins=*",
                f"--user-data-dir={self.user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ]
        )
        tabs = None
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.debug_port}/json/list"))
                if tabs:
                    break
            except Exception:
                time.sleep(0.2)
        if not tabs:
            raise RuntimeError("Impossibile aprire il canale DevTools di Edge.")
        page = next((t for t in tabs if t.get("type") == "page"), None)
        if page is None:
            raise RuntimeError("Nessuna pagina Edge disponibile per il debug.")
        self.websocket = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.send("Network.enable")
        if download_dir is not None:
            self.send("Browser.setDownloadBehavior", {
                "behavior": "allow",
                "downloadPath": str(download_dir),
                "eventsEnabled": True,
            })

    def close(self) -> None:
        try:
            if self.websocket is not None:
                self.websocket.close()
        except Exception:
            pass
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
        shutil.rmtree(self.user_data_dir, ignore_errors=True)

    def _recv_until_id(self, message_id: int) -> dict:
        while True:
            response = json.loads(self.websocket.recv())
            if response.get("id") == message_id:
                return response
            if response.get("method"):
                self._events.append(response)

    def send(self, method: str, params: dict | None = None) -> dict:
        message_id = next(self._message_ids)
        self.websocket.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        return self._recv_until_id(message_id)

    def wait(self, seconds: float) -> None:
        time.sleep(seconds)

    def navigate(self, url: str, wait_seconds: float = 0) -> None:
        self.send("Page.navigate", {"url": url})
        if wait_seconds:
            self.wait(wait_seconds)

    def evaluate(self, expression: str, await_promise: bool = False):
        result = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": await_promise},
        )
        return result["result"]["result"].get("value")

    def take_events(self) -> list[dict]:
        """Scarica gli eventi CDP ricevuti dall'ultima lettura."""
        events = self._events
        self._events = []
        return events

    def get_cookies(self, urls: list[str]) -> list[dict]:
        return self.send("Network.getCookies", {"urls": urls})["result"]["cookies"]

    def set_cookies(self, cookies: list[dict]) -> None:
        payload = []
        for cookie in cookies:
            item = {
                "name": cookie["name"],
                "value": cookie["value"],
            }
            if cookie.get("domain"):
                item["domain"] = cookie["domain"]
            if cookie.get("path"):
                item["path"] = cookie["path"]
            if cookie.get("expires"):
                item["expires"] = cookie["expires"]
            if cookie.get("httpOnly") is not None:
                item["httpOnly"] = cookie["httpOnly"]
            if cookie.get("secure") is not None:
                item["secure"] = cookie["secure"]
            if cookie.get("sameSite"):
                item["sameSite"] = cookie["sameSite"]
            payload.append(item)
        if payload:
            self.send("Network.setCookies", {"cookies": payload})


EDGE_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path.home() / r"AppData\Local\Microsoft\Edge\Application\msedge.exe",
]


def detect_edge_path(config: dict) -> Path:
    configured = config.get("nares", {}).get("edge_path")
    if configured:
        candidate = Path(str(configured))
        if candidate.exists():
            return candidate
    for candidate in EDGE_CANDIDATES:
        if candidate.exists():
            return candidate
    raise ConfigError(
        "Microsoft Edge non trovato. Imposta 'nares.edge_path' in config.json "
        "(es. C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe)."
    )


class NaresSession:
    """Sessione NARES: riusa i cookie salvati, altrimenti fa login con Edge."""

    def __init__(self, config: dict, credentials: dict, session_cache: Path) -> None:
        self.config = config
        self.credentials = credentials
        self.session_cache = session_cache
        self.browser: CdpBrowser | None = None

    # -- cache sessione -----------------------------------------------------
    def _load_cache(self) -> list[dict] | None:
        if not self.session_cache.exists():
            return None
        try:
            data = json.loads(self.session_cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        cookies = data.get("cookies")
        if not isinstance(cookies, list) or not cookies:
            return None
        if data.get("expires_at") and datetime.fromisoformat(data["expires_at"]) < datetime.now():
            return None
        return cookies

    def _save_cache(self, cookies: list[dict]) -> None:
        payload = {
            "cached_at": datetime.now().isoformat(timespec="seconds"),
            # la password NARES cambia ogni 3 mesi: scadenza prudenziale della sessione
            "expires_at": (datetime.now().replace(month=datetime.now().month + 2)).isoformat(timespec="seconds"),
            "cookies": cookies,
        }
        self.session_cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _clear_cache(self) -> None:
        try:
            self.session_cache.unlink(missing_ok=True)
        except OSError:
            pass

    # -- login ---------------------------------------------------------------
    def _is_authenticated(self, cookies: list[dict]) -> bool:
        import requests

        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"), path=cookie.get("path", "/"))
        base = self.config.get("nares", {}).get("main_url", "")
        if not base:
            return False
        try:
            response = session.get(base, timeout=20, allow_redirects=True)
            return response.status_code == 200 and "login" not in response.url.lower()
        except Exception:
            return False

    def login(self) -> list[dict]:
        cached = self._load_cache()
        if cached and self._is_authenticated(cached):
            return cached
        self._clear_cache()

        browser = CdpBrowser(detect_edge_path(self.config))
        self.browser = browser
        try:
            browser.start()
            self._do_login(browser)
            cookies = browser.get_cookies([self.config["nares"]["portal_base"]])
        finally:
            browser.close()
            self.browser = None
        self._save_cache(cookies)
        return cookies

    def _do_login(self, browser: CdpBrowser) -> None:
        nares = self.config["nares"]
        selectors = nares["selectors"]
        browser.navigate(nares["login_url"], wait_seconds=6)

        preflight = browser.evaluate(
            """
        (() => {
          const href = location.href || "";
          const title = document.title || "";
          const body = (document.body && document.body.innerText ? document.body.innerText : "").slice(0, 1000);
          return {
            href,
            title,
            body,
            hasUsername: !!document.querySelector("input[name='username']"),
            hasPassword: !!document.querySelector("input[name='password']"),
            hasEnter: !!(document.querySelector("#enterAuthentik") ||
              [...document.querySelectorAll("button,input[type=submit],input[type=button]")]
                .find(b => /enter/i.test(b.innerText || b.value || "")))
          };
        })()
        """
        ) or {}
        body_text = str(preflight.get("body") or "")
        title = str(preflight.get("title") or "")
        href = str(preflight.get("href") or "")

        if "chrome-error://" in href or "DNS_PROBE_FINISHED_NXDOMAIN" in body_text:
            raise RuntimeError(
                f"Login NARES: URL non raggiungibile ({href or nares['login_url']}). "
                "Controlla host/path in config.json."
            )
        if "404 Not Found" in title or "404 Not Found" in body_text:
            raise RuntimeError(
                f"Login NARES: pagina non trovata ({href or nares['login_url']}). "
                "Verifica login_url in config.json."
            )

        if preflight.get("hasEnter") and not (preflight.get("hasUsername") and preflight.get("hasPassword")):
            enter_result = browser.evaluate(
                """
            (() => {
              const btn = document.querySelector("#enterAuthentik") ||
                [...document.querySelectorAll("button,input[type=submit],input[type=button]")]
                  .find(b => /enter/i.test(b.innerText || b.value || ""));
              if (!btn) return "ENTER_NOT_FOUND";
              btn.click();
              return "ENTER_CLICKED";
            })()
            """
            )
            if enter_result != "ENTER_CLICKED":
                raise RuntimeError(
                    f"Login NARES: pulsante ENTER non trovato ({enter_result}). Verifica i selettori/config."
                )
            browser.wait(8)

        username_stage = f"""
        (() => {{
          const setValue = (element, value) => {{
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
            setter.call(element, value);
            element.dispatchEvent(new Event("input", {{ bubbles: true }}));
            element.dispatchEvent(new Event("change", {{ bubbles: true }}));
          }};
          const stage = document.querySelector("ak-flow-executor")?.shadowRoot?.querySelector("ak-stage-identification");
          const root = stage?.shadowRoot;
          if (!root) return "STAGE_NOT_FOUND";
          const user = root.querySelector("input[name='uidField']");
          const btn = root.querySelector("button[type='submit']");
          if (!user || !btn) return "USERNAME_STAGE_FIELDS_NOT_FOUND";
          setValue(user, {self.credentials["username"]!r});
          btn.click();
          return "USERNAME_SUBMITTED";
        }})()
        """
        username_result = browser.evaluate(username_stage)
        if username_result == "USERNAME_SUBMITTED":
            browser.wait(6)

        fill = f"""
        (() => {{
          const setValue = (element, value) => {{
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
            setter.call(element, value);
            element.dispatchEvent(new Event("input", {{ bubbles: true }}));
            element.dispatchEvent(new Event("change", {{ bubbles: true }}));
          }};
          const passwordStage = document.querySelector("ak-flow-executor")?.shadowRoot?.querySelector("ak-stage-password");
          const passwordRoot = passwordStage?.shadowRoot;
          const pwd = passwordRoot?.querySelector("input[name='password']") ||
                      document.querySelector({selectors["password_input"]!r});
          const btn = passwordRoot?.querySelector("button[type='submit']") ||
                      document.querySelector({selectors["login_button"]!r}) ||
                      [...document.querySelectorAll("button")].find(b => /entra|login|accedi|invia|continua/i.test(b.innerText));
          const user = document.querySelector({selectors["username_input"]!r});
          if (!pwd) return "PASSWORD_NOT_FOUND";
          if (user) setValue(user, {self.credentials["username"]!r});
          setValue(pwd, {self.credentials["password"]!r});
          if (btn) {{
            btn.click();
            return "SUBMITTED";
          }}
          pwd.dispatchEvent(new KeyboardEvent("keydown", {{ key: "Enter", code: "Enter", bubbles: true }}));
          pwd.dispatchEvent(new KeyboardEvent("keypress", {{ key: "Enter", code: "Enter", bubbles: true }}));
          pwd.dispatchEvent(new KeyboardEvent("keyup", {{ key: "Enter", code: "Enter", bubbles: true }}));
          return "SUBMITTED";
        }})()
        """
        result = browser.evaluate(fill)
        if result != "SUBMITTED":
            details = browser.evaluate(
                """
            (() => ({
              href: location.href || "",
              title: document.title || "",
              body: (document.body && document.body.innerText ? document.body.innerText : "").slice(0, 1000)
            }))()
            """
            ) or {}
            raise RuntimeError(
                f"Login NARES: campi non trovati ({result}). URL={details.get('href', '')}. "
                "Verifica login_url e selettori in config.json."
            )
        browser.wait(10)
        current_url = str(browser.evaluate("location.href") or "")
        if "login" in current_url.lower() or "flow/auth" in current_url.lower():
            raise RuntimeError(
                f"Login NARES fallito (URL rimasto sulla pagina di login: {current_url}). "
                "Controlla le credenziali in .env."
            )

    def download(self, download_dir: Path, wait_max: float = 120.0) -> list[Path]:
        """Restituisce i file scaricati nella cartella durante l'esecuzione della callback."""
        return []


def load_or_login(config: dict, credentials: dict, session_cache: Path | None = None) -> tuple[NaresSession, list[dict]]:
    session = NaresSession(config, credentials, session_cache or Path.cwd() / SESSION_CACHE_NAME)
    cookies = session.login()
    return session, cookies
