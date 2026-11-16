"""Background file watcher using watchfiles."""

import threading
import asyncio
from pathlib import Path
import logging
from typing import Callable
from watchfiles import watch, Change

from server.vaultmcp.vault.paths import PROTECTED_DIRS

logger = logging.getLogger("vaultmcp")


class VaultWatcher:
    """Watches the vault folder for file updates in a background thread."""

    def __init__(self, vault_root: Path, on_change: Callable[[], None], debounce_seconds: float = 1.5):
        self.vault_root = vault_root.resolve()
        self.on_change = on_change
        self.debounce_seconds = debounce_seconds
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="VaultWatcherThread")
        self._thread.start()
        logger.info("Vault watcher started for %s", self.vault_root)

    def stop(self) -> None:
        self._stop_event.set()
        logger.info("Vault watcher stopped")

    def _watch_loop(self) -> None:
        try:
            for changes in watch(str(self.vault_root), debounce=int(self.debounce_seconds * 1000), stop_event=self._stop_event):
                if self._stop_event.is_set():
                    break

                relevant = False
                for change_type, path_str in changes:
                    p = Path(path_str)
                    try:
                        rel = p.relative_to(self.vault_root)
                        parts = rel.parts
                        if any(part in PROTECTED_DIRS for part in parts):
                            continue
                        if p.suffix == ".md" or change_type == Change.deleted:
                            relevant = True
                            break
                    except ValueError:
                        continue

                if relevant:
                    logger.info("Changes detected by watcher, triggering index update...")
                    try:
                        self.on_change()
                    except Exception as e:
                        logger.error("Watcher callback error: %s", str(e))
        except Exception as e:
            logger.error("Watcher thread encountered error: %s", str(e))
