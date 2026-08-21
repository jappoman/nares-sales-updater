"""GUI per NARES Sales Updater (eseguibile con PyInstaller, modalità manuale).

Permette di inserire date custom ed eseguire il flusso completo: download da
NARES, pulizia, generazione SQL e (se spuntato) scrittura sul DB SQL Server.
La scrittura sul DB è SPENTA di default (dry-run): spunta la checkbox per abilitarla.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import traceback
from datetime import date, timedelta
from pathlib import Path
from tkinter import messagebox, scrolledtext

from main import run_job
from nares_sales_updater import config as cfg
from nares_sales_updater.log_util import create_run_logger

APP_DIR = cfg.APP_DIR


class NaresUpdaterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("NARES Sales Updater")
        self.root.geometry("800x560")
        self.root.minsize(720, 500)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.current_log_path: Path | None = None

        today = date.today()
        default_from = today - timedelta(days=int(cfg.load_config(cfg.CONFIG_PATH).get("exports", {}).get("orders", {}).get("date_from_offset_days", 120)))
        default_to = today - timedelta(days=1)

        container = tk.Frame(root, padx=16, pady=16)
        container.pack(fill="both", expand=True)

        title = tk.Label(container, text="Caricamento dati NARES", font=("Segoe UI", 16, "bold"), anchor="w")
        title.pack(fill="x")

        subtitle = tk.Label(
            container,
            text="Inserisci il range di date delle estrazioni e premi Avvia. "
                 "Gli ingressi (rapportino visite) usano l'anno del range.",
            font=("Segoe UI", 10), anchor="w", justify="left",
        )
        subtitle.pack(fill="x", pady=(6, 14))

        form = tk.Frame(container)
        form.pack(fill="x")

        tk.Label(form, text="Data da", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.date_from_var = tk.StringVar(value=default_from.isoformat())
        self.date_from_entry = tk.Entry(form, textvariable=self.date_from_var, width=16, font=("Consolas", 11))
        self.date_from_entry.grid(row=1, column=0, sticky="w", padx=(0, 16), pady=(4, 0))

        tk.Label(form, text="Data a", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w")
        self.date_to_var = tk.StringVar(value=default_to.isoformat())
        self.date_to_entry = tk.Entry(form, textvariable=self.date_to_var, width=16, font=("Consolas", 11))
        self.date_to_entry.grid(row=1, column=1, sticky="w", pady=(4, 0))

        self.execute_db_var = tk.BooleanVar(value=False)  # dry-run di default: sicurezza
        self.execute_db_check = tk.Checkbutton(
            form,
            text="Scrivi sul database (SQL Server) — ATTENZIONE: scrive dati reali",
            variable=self.execute_db_var,
            font=("Segoe UI", 10),
        )
        self.execute_db_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))

        buttons = tk.Frame(container)
        buttons.pack(fill="x", pady=(16, 12))

        self.run_button = tk.Button(
            buttons, text="Avvia estrazione", width=18, height=2, command=self.start_job,
            bg="#0f766e", fg="white", activebackground="#115e59", activeforeground="white",
        )
        self.run_button.pack(side="left")

        self.open_folder_button = tk.Button(buttons, text="Apri cartella", width=16, command=self.open_output_folder)
        self.open_folder_button.pack(side="left", padx=(10, 0))

        self.status_var = tk.StringVar(value="Pronto.")
        status = tk.Label(container, textvariable=self.status_var, anchor="w", font=("Segoe UI", 10, "italic"))
        status.pack(fill="x", pady=(0, 10))

        self.log_text = scrolledtext.ScrolledText(container, wrap="word", font=("Consolas", 10), state="disabled")
        self.log_text.pack(fill="both", expand=True)

        self.set_running(False)
        self.date_from_entry.focus_set()
        self.root.after(200, self.flush_log_queue)

    # -- log -----------------------------------------------------------------
    def append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def enqueue_log(self, message: str) -> None:
        self.log_queue.put(message)

    def flush_log_queue(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.append_log(message)
        self.root.after(200, self.flush_log_queue)

    def set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.run_button.configure(state=state)
        self.date_from_entry.configure(state=state)
        self.date_to_entry.configure(state=state)
        self.execute_db_check.configure(state=state)

    def open_output_folder(self) -> None:
        try:
            import os
            os.startfile(APP_DIR)
        except Exception as exc:
            messagebox.showerror("Errore", f"Impossibile aprire la cartella:\n{exc}")

    # -- esecuzione -----------------------------------------------------------
    def start_job(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        date_from = self.date_from_var.get().strip()
        date_to = self.date_to_var.get().strip()
        if not date_from or not date_to:
            messagebox.showwarning("Date mancanti", "Inserisci sia Data da sia Data a.")
            return

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        run_logger = create_run_logger(sink=self.enqueue_log, prefix="gui", logs_dir=APP_DIR / "logs")
        self.current_log_path = run_logger.log_path
        self.status_var.set("Estrazione in corso...")
        self.set_running(True)

        self.worker = threading.Thread(
            target=self.run_worker,
            args=(date_from, date_to, self.execute_db_var.get(), run_logger),
            daemon=True,
        )
        self.worker.start()

    def run_worker(self, date_from: str, date_to: str, write_db: bool, run_logger) -> None:
        try:
            run_logger(f"Cartella di lavoro: {APP_DIR}")
            run_logger(f"Range richiesto: {date_from} -> {date_to}")
            run_logger(f"Log esecuzione: {run_logger.log_path}")
            if not write_db:
                run_logger("Scrittura sul database DISATTIVATA (dry-run).")
            result = run_job(
                date_from, date_to,
                live=write_db, yes=True,
                out_dir=str(APP_DIR / "out"),
                logger=run_logger,
            )
        except Exception as exc:
            run_logger(f"Errore non gestito nella GUI: {exc}")
            run_logger(traceback.format_exc().rstrip())
            result = 1
        self.root.after(0, self.finish_run, result)

    def finish_run(self, result: int) -> None:
        self.set_running(False)
        self.date_from_entry.focus_set()
        if result == 0:
            self.status_var.set("Estrazione completata.")
            messagebox.showinfo(
                "Completato",
                f"Estrazione completata con successo.\nLog: {self.current_log_path}"
                if self.current_log_path else "Estrazione completata con successo.",
            )
        else:
            self.status_var.set("Estrazione terminata con errori.")
            messagebox.showerror(
                "Errore",
                f"L'estrazione non è andata a buon fine. Controlla il log:\n{self.current_log_path}"
                if self.current_log_path else "L'estrazione non è andata a buon fine.",
            )


def main() -> None:
    root = tk.Tk()
    app = NaresUpdaterApp(root)
    app.append_log("Pronto. Configura le date e premi Avvia estrazione.")
    root.mainloop()


if __name__ == "__main__":
    main()
