"""Steam CEF debugging discovery and recent Store patch diagnostics."""

from collections import deque
import os
from pathlib import Path
import time

# The Store patch runs in Uran's Decky process, but the people looking at the
# state (ASSella, the AT0-M console) talk to Epsilon — a different process. A
# small file next to the shared settings lets both sides read the same recent
# trace instead of each showing its own empty buffer.
#
# The path is supplied by the caller: Decky runs as root on a Steam Deck, so
# ``Path.home()`` here would resolve to /root and the user's Epsilon service
# would never see the file. ``services.build`` passes the Settings directory,
# which both processes already resolve identically.
LOG_FILENAME = "store_patch.log"
LOG_MAX_BYTES = 64 * 1024
LOG_TAIL = 12


class StoreDebugger:
    def __init__(self, http, logger, ports=range(8080, 8083), log_path: Path | None = None):
        self.http = http
        self.logger = logger
        self.ports = tuple(ports)
        self._log_path = Path(log_path) if log_path is not None else None
        self._cached_at = 0.0
        self._cached_status = None
        self._logs = deque(maxlen=40)

    @property
    def log_path(self) -> Path | None:
        return self._log_path

    def record_log(self, message: str) -> None:
        if "[StorePatch]" not in message:
            return
        line = str(message)[-500:]
        self._logs.append(line)
        self._append_to_file(line)

    def _append_to_file(self, line: str) -> None:
        """Append one trace line, keeping the newest history on rollover.

        Truncating to zero bytes would erase the failure the trace exists to
        explain, so a rollover keeps the most recent lines instead.
        """
        if self._log_path is None:
            return
        try:
            # Never create the directory: a root-run Uran would leave a
            # root-owned directory the user's Epsilon could not write to.
            if not self._log_path.parent.is_dir():
                return
            if self._log_path.is_file() and self._log_path.stat().st_size > LOG_MAX_BYTES:
                self._trim()
            created = not self._log_path.exists()
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%H:%M:%S')} {line}\n")
            if created:
                # A root-run Uran must leave a trace the user's Epsilon can
                # read, whatever decky's umask happens to be.
                try:
                    os.chmod(self._log_path, 0o644)
                except OSError:
                    pass
        except OSError:
            pass

    def _trim(self) -> None:
        """Rewrite the file with its newest lines, under half the size cap."""
        lines = self._log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        kept: list[str] = []
        total = 0
        for line in reversed(lines):
            total += len(line) + 1
            if total > LOG_MAX_BYTES // 2:
                break
            kept.append(line)
        kept.reverse()
        self._log_path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    def recent_logs(self, limit: int = LOG_TAIL) -> list[str]:
        """The last trace lines, whoever wrote them."""
        if self._log_path is None:
            return []
        try:
            lines = self._log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        return [line for line in lines if line.strip()][-limit:]

    def status(self, refresh: bool = False) -> dict:
        now = time.monotonic()
        if not refresh and self._cached_status and now - self._cached_at < 8:
            result = {key: value for key, value in self._cached_status.items() if not key.startswith("_")}
            result["logs"] = list(self._logs)
            return result

        for port in self.ports:
            try:
                response = self.http.get(f"http://localhost:{port}/json", timeout=0.4)
                if not response.ok:
                    continue
                tabs = response.json()
                store_tab = next(
                    (
                        tab for tab in tabs
                        if "store.steampowered.com/" in str(tab.get("url", ""))
                        and tab.get("webSocketDebuggerUrl")
                    ),
                    None,
                )
                result = {
                    "available": True,
                    "port": port,
                    "store_tab": bool(store_tab),
                    "url": (store_tab or {}).get("url", ""),
                    "_websocket_url": (store_tab or {}).get("webSocketDebuggerUrl"),
                    "target_count": len(tabs),
                    "checked_at": int(time.time()),
                }
                if store_tab:
                    result["message"] = "Steam Store page detected. Uran is trying the button injection; Valve's current page layout may affect placement."
                else:
                    result["message"] = "CEF debugging is available; open a Steam Store page to check your webview."
                self._cache(result)
                return {
                    **{key: value for key, value in result.items() if not key.startswith("_")},
                    "logs": list(self._logs),
                }
            except Exception:
                continue

        result = {
            "available": False,
            "port": None,
            "store_tab": False,
            "url": "",
            "target_count": 0,
            "checked_at": int(time.time()),
            "message": "CEF debugging was not detected on ports 8080–8082. The Store button cannot be injected until Steam exposes its debugging port.",
        }
        self._cache(result)
        return {**result, "logs": list(self._logs)}

    def discover(self) -> dict | None:
        status = self.status()
        if not status.get("store_tab"):
            return None
        return {
            "webSocketDebuggerUrl": (self._cached_status or {}).get("_websocket_url"),
            "url": status["url"],
        }

    def _cache(self, result: dict) -> None:
        self._cached_status = dict(result)
        self._cached_at = time.monotonic()