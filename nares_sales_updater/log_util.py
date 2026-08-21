"""Run logger: writes a timestamped log line to file and optionally to a sink."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


class RunLogger:
    def __init__(self, log_path: Path, sink=None) -> None:
        self.log_path = log_path
        self.sink = sink

    def __call__(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        if self.sink is not None:
            self.sink(line)


def create_run_logger(sink=None, prefix: str = "run", logs_dir: Path | None = None) -> RunLogger:
    base = logs_dir or (Path.cwd() / "logs")
    base.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = base / f"{prefix}_{timestamp}.log"
    return RunLogger(log_path, sink=sink)
