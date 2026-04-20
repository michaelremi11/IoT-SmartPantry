"""
hub/services/sku_client.py
Async SKU lookup client with offline SQLite cache and automatic sync.

Architecture
------------

ONLINE path (Wi-Fi available):
  Scanner → lookup_sku_async() → GET /lookup/{sku} (FastAPI) → Firestore
            ↳ result returned to Kivy UI

OFFLINE path (no network / FastAPI unreachable):
  Scanner → lookup_sku_async() → network error detected
            ↳ scan saved to SQLite cache (hub/data/sku_cache.db)
            ↳ Kivy UI shows "📶 Offline — scan saved" status

SYNC path (network restored):
  Background reconnection monitor detects connectivity
            ↳ Reads all un-synced rows from SQLite
            ↳ POSTs each queued scan to FastAPI /lookup/{sku}
            ↳ Marks rows as synced (or retires after max_retries)
            ↳ Kivy UI is notified of resync count

SQLite Schema (hub/data/sku_cache.db)
--------------------------------------

  CREATE TABLE pending_scans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku         TEXT NOT NULL,
    queued_at   TEXT NOT NULL,      -- ISO-8601 UTC
    synced      INTEGER DEFAULT 0,  -- 0 = pending, 1 = synced
    retry_count INTEGER DEFAULT 0,
    last_error  TEXT
  );

Usage
-----
  from hub.services.sku_client import lookup_sku_async, start_sync_monitor

  # Wire up in App.build():
  start_sync_monitor(on_sync=lambda n: app._on_sync_complete(n))

  # On each barcode scan:
  lookup_sku_async(sku, on_success=..., on_error=...)
"""

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from kivy.clock import Clock

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BRAIN_API_URL    = os.getenv("BRAIN_API_URL", "http://127.0.0.1:8000")
LOOKUP_TIMEOUT   = float(os.getenv("SKU_LOOKUP_TIMEOUT_S",  "8.0"))
SYNC_INTERVAL    = int(os.getenv("SKU_SYNC_INTERVAL_S",     "30"))
MAX_RETRIES      = int(os.getenv("SKU_MAX_RETRIES",          "5"))

# SQLite file lives beside the hub package
_DB_PATH = Path(os.getenv(
    "SKU_CACHE_DB",
    str(Path(__file__).resolve().parent.parent.parent / "hub" / "data" / "sku_cache.db"),
))

# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    """Return a thread-local SQLite connection (WAL mode for concurrency)."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_scans (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sku         TEXT    NOT NULL,
            queued_at   TEXT    NOT NULL,
            synced      INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            last_error  TEXT
        )
    """)
    conn.commit()


def _enqueue_scan(sku: str):
    """Persist a scan that failed due to network unavailability."""
    conn = _get_conn()
    _ensure_schema(conn)
    conn.execute(
        "INSERT INTO pending_scans (sku, queued_at) VALUES (?, ?)",
        (sku, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    logger.info("[SKUClient] 💾 Queued offline scan: %s", sku)


def _get_pending(conn: sqlite3.Connection) -> list[tuple]:
    """Return rows: (id, sku, retry_count) for un-synced scans below max retries."""
    cur = conn.execute(
        "SELECT id, sku, retry_count FROM pending_scans "
        "WHERE synced = 0 AND retry_count < ? ORDER BY queued_at ASC",
        (MAX_RETRIES,),
    )
    return cur.fetchall()


def _mark_synced(conn: sqlite3.Connection, row_id: int):
    conn.execute("UPDATE pending_scans SET synced = 1 WHERE id = ?", (row_id,))
    conn.commit()


def _increment_retry(conn: sqlite3.Connection, row_id: int, error: str):
    conn.execute(
        "UPDATE pending_scans SET retry_count = retry_count + 1, last_error = ? WHERE id = ?",
        (error, row_id),
    )
    conn.commit()


def pending_scan_count() -> int:
    """Return the number of un-synced scans in the local cache. Safe to call anytime."""
    try:
        conn = _get_conn()
        _ensure_schema(conn)
        cur  = conn.execute("SELECT COUNT(*) FROM pending_scans WHERE synced = 0")
        n    = cur.fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Connectivity check
# ---------------------------------------------------------------------------

def _is_online() -> bool:
    """
    Lightweight connectivity test: attempt a TCP connection to the FastAPI host.
    Returns True if the brain API is reachable.  No HTTP overhead.
    """
    import socket
    host = BRAIN_API_URL.replace("http://", "").replace("https://", "").split(":")[0]
    port = 8000
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Core lookup worker
# ---------------------------------------------------------------------------

def _do_lookup(sku: str) -> dict:
    """
    Execute a synchronous GET /lookup/{sku} against the FastAPI service.
    Raises an exception on any failure (caller decides how to handle).
    """
    import httpx
    url = f"{BRAIN_API_URL}/lookup/{sku}"
    logger.info("[SKUClient] GET %s", url)
    with httpx.Client(timeout=LOOKUP_TIMEOUT) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# Public async lookup (main API)
# ---------------------------------------------------------------------------

def lookup_sku_async(
    sku: str,
    on_success: Callable[[dict], None],
    on_error: Optional[Callable[[str], None]] = None,
    on_offline: Optional[Callable[[str], None]] = None,
) -> None:
    """
    Fire-and-forget SKU lookup with automatic offline fallback.

    Flow:
      1. Attempt GET /lookup/{sku} against the local FastAPI service.
      2. On success → call on_success(data) on the Kivy main thread.
      3. On network error:
           a. Save scan to SQLite cache via _enqueue_scan().
           b. Call on_offline("📶 Offline — scan saved. Will sync when reconnected.")
              (falls back to on_error if on_offline is not provided).

    All callbacks are delivered on the **Kivy main thread** via Clock.

    Parameters
    ----------
    sku        : Barcode / SKU string from the scanner.
    on_success : Called with the API response dict on success.
    on_error   : Called with an error string for non-network failures (e.g. 404).
    on_offline : Called with a user-friendly message when the scan is cached offline.
                 If omitted, on_error is used.
    """
    def _worker():
        try:
            data = _do_lookup(sku)
            logger.info("[SKUClient] ✅ %s → %s", sku, data.get("product_name"))
            Clock.schedule_once(lambda dt: on_success(data))

        except Exception as exc:
            error_str = str(exc)
            logger.error("[SKUClient] ❌ Lookup failed for %s: %s", sku, error_str)

            # Classify: network error or API-level error?
            is_network_error = _classify_network_error(exc)

            if is_network_error:
                _enqueue_scan(sku)
                msg = (
                    f"📶 Offline — '{sku}' saved locally. "
                    f"Will sync when connection is restored. "
                    f"({pending_scan_count()} scan(s) queued)"
                )
                callback = on_offline or on_error
                if callback:
                    Clock.schedule_once(lambda dt: callback(msg))
            else:
                # API reachable but product not found or server error
                if on_error:
                    Clock.schedule_once(lambda dt: on_error(error_str))

    t = threading.Thread(target=_worker, daemon=True, name=f"sku-lookup-{sku[:8]}")
    t.start()


def _classify_network_error(exc: Exception) -> bool:
    """
    Return True for errors that indicate network unavailability.
    False for 404 / 422 / server errors where the API is reachable.
    """
    import httpx
    import socket

    if isinstance(exc, (
        httpx.ConnectError,
        httpx.TimeoutException,
        httpx.NetworkError,
        socket.timeout,
        ConnectionRefusedError,
        OSError,
    )):
        return True

    # httpx HTTP status errors — API is up but returned an error code
    if isinstance(exc, httpx.HTTPStatusError):
        return False

    # Catch-all: treat unknown errors as network failures (safer for offline mode)
    return True


# ---------------------------------------------------------------------------
# Background sync monitor
# ---------------------------------------------------------------------------

_sync_thread: Optional[threading.Thread] = None
_stop_sync   = threading.Event()


def start_sync_monitor(
    on_sync: Optional[Callable[[int], None]] = None,
    poll_interval: int = SYNC_INTERVAL,
) -> None:
    """
    Start a background thread that periodically checks for connectivity and,
    when online, flushes pending SQLite scans to the FastAPI service.

    Call once from App.build() after the Kivy window exists.

    Parameters
    ----------
    on_sync       : Optional callback(n_synced: int) delivered on the Kivy
                    main thread when scans are successfully flushed.
    poll_interval : Seconds between connectivity checks (default: 30).
    """
    global _sync_thread, _stop_sync
    _stop_sync.clear()

    def _monitor():
        logger.info("[SKUClient] 🔄 Sync monitor started (poll every %ds)", poll_interval)
        while not _stop_sync.is_set():
            _stop_sync.wait(timeout=poll_interval)
            if _stop_sync.is_set():
                break
            try:
                _run_sync_cycle(on_sync)
            except Exception as exc:
                logger.error("[SKUClient] Sync cycle error: %s", exc)

    _sync_thread = threading.Thread(
        target=_monitor, daemon=True, name="sku-sync-monitor"
    )
    _sync_thread.start()


def stop_sync_monitor():
    """Stop the background sync monitor. Call from App.on_stop()."""
    _stop_sync.set()


def _run_sync_cycle(on_sync: Optional[Callable[[int], None]]):
    """
    One sync cycle:
      1. Check connectivity.
      2. If online: attempt to POST each pending scan to FastAPI.
      3. Mark successful rows as synced; increment retry count on failures.
      4. Invoke on_sync callback if any scans were flushed.
    """
    if not _is_online():
        n = pending_scan_count()
        if n > 0:
            logger.info("[SKUClient] 📵 Still offline. %d scan(s) queued.", n)
        return

    conn = _get_conn()
    _ensure_schema(conn)
    pending = _get_pending(conn)

    if not pending:
        conn.close()
        return

    logger.info("[SKUClient] 📡 Back online! Syncing %d queued scan(s)…", len(pending))
    synced_count = 0

    for row_id, sku, retry_count in pending:
        try:
            _do_lookup(sku)  # This also writes to Firestore (side-effect in FastAPI)
            _mark_synced(conn, row_id)
            synced_count += 1
            logger.info("[SKUClient]   ✅ Synced queued scan: %s", sku)
        except Exception as exc:
            err = str(exc)
            _increment_retry(conn, row_id, err)
            logger.warning(
                "[SKUClient]   ⚠️  Failed to sync %s (attempt %d/%d): %s",
                sku, retry_count + 1, MAX_RETRIES, err,
            )

    conn.close()

    if synced_count > 0 and on_sync:
        Clock.schedule_once(lambda dt: on_sync(synced_count))


# ---------------------------------------------------------------------------
# Cache inspection utility (for debugging / status screen)
# ---------------------------------------------------------------------------

def get_cache_stats() -> dict:
    """
    Return a summary of the local SQLite cache state.
    Safe to call from any thread.

    Returns
    -------
    {
      "pending":    int,  # un-synced scans
      "synced":     int,  # successfully flushed scans (historical)
      "exhausted":  int,  # scans that hit max retries
      "db_path":    str,
    }
    """
    try:
        conn = _get_conn()
        _ensure_schema(conn)
        stats = {}
        for label, query in [
            ("pending",   "SELECT COUNT(*) FROM pending_scans WHERE synced = 0 AND retry_count < ?"),
            ("exhausted", "SELECT COUNT(*) FROM pending_scans WHERE synced = 0 AND retry_count >= ?"),
            ("synced",    "SELECT COUNT(*) FROM pending_scans WHERE synced = 1"),
        ]:
            if "?" in query:
                cur = conn.execute(query, (MAX_RETRIES,))
            else:
                cur = conn.execute(query)
            stats[label] = cur.fetchone()[0]
        conn.close()
        stats["db_path"] = str(_DB_PATH)
        return stats
    except Exception as exc:
        return {"error": str(exc), "db_path": str(_DB_PATH)}
