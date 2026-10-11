"""Steam CEF debugging discovery and recent Store patch diagnostics."""

from collections import deque
import time


class StoreDebugger:
    def __init__(self, http, logger, ports=range(8080, 8083)):
        self.http = http
        self.logger = logger
        self.ports = tuple(ports)
        self._cached_at = 0.0
        self._cached_status = None
        self._logs = deque(maxlen=40)

    def record_log(self, message: str) -> None:
        if "[StorePatch]" not in message:
            return
        self._logs.append(str(message)[-500:])

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
                    result["message"] = "CEF debugging is available; open a Steam Store page to check its webview."
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
