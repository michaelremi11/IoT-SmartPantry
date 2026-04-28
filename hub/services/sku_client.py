"""
hub/services/sku_client.py
Async SKU lookup client with offline SQLite cache and automatic sync.

Architecture
------------

ONLINE path (Wi-Fi available):
  Scanner → auto_add_sku_async() → Open Food Facts → Firestore
            ↳ pantryItems is created/restocked and usageLogs is appended

OFFLINE path (no network / lookup unreachable):
  Scanner → auto_add_sku_async() → network error detected
            ↳ scan saved to SQLite cache (hub/data/sku_cache.db)
            ↳ Kivy UI shows "📶 Offline — scan saved" status

SYNC path (network restored):
  Background reconnection monitor detects connectivity
            ↳ Reads all un-synced rows from SQLite
            ↳ re-runs product lookup and auto-adds/restocks in Firestore
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
  from hub.services.sku_client import auto_add_sku_async, start_sync_monitor

  # Wire up in App.build():
  start_sync_monitor(on_sync=lambda n: app._on_sync_complete(n))

  # On each barcode scan:
  auto_add_sku_async(sku, on_success=..., on_error=...)
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

from hub.firebase import get_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOOKUP_TIMEOUT   = float(os.getenv("SKU_LOOKUP_TIMEOUT_S",  "8.0"))
SYNC_INTERVAL    = int(os.getenv("SKU_SYNC_INTERVAL_S",     "30"))
MAX_RETRIES      = int(os.getenv("SKU_MAX_RETRIES",          "5"))
OFF_BASE         = os.getenv("OPEN_FOOD_FACTS_BASE_URL", "https://world.openfoodfacts.org/api/v2/product")
OFF_FIELDS       = "product_name,quantity,categories_tags,brands,nutriments,image_url"
PANTRY_COLLECTION = os.getenv("FIRESTORE_PANTRY_COLLECTION", "pantryItems")
USAGE_LOGS_COLLECTION = os.getenv("FIRESTORE_USAGE_LOGS_COLLECTION", "usageLogs")
HOUSEHOLD_ID = os.getenv("SMART_PANTRY_HOUSEHOLD_ID", "default")

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
    Lightweight connectivity test against Open Food Facts.
    Returns True if product lookup is reachable. No HTTP overhead.
    """
    import socket
    host = OFF_BASE.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
    port = 443 if OFF_BASE.startswith("https://") else 80
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
    Execute a synchronous product lookup and cache the response in Firestore.
    Raises an exception on any failure (caller decides how to handle).
    """
    import httpx
    url = f"{OFF_BASE}/{sku}.json?fields={OFF_FIELDS}"
    logger.info("[SKUClient] GET %s", url)
    with httpx.Client(timeout=LOOKUP_TIMEOUT) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()

    if payload.get("status") != 1:
        raise httpx.HTTPStatusError(
            f"SKU '{sku}' not found in Open Food Facts",
            request=response.request,
            response=response,
        )

    product = payload.get("product", {})
    quantity_str = product.get("quantity") or ""
    qty_value = None
    qty_unit = "unit"
    parts = quantity_str.strip().split()
    if parts:
        try:
            qty_value = float(parts[0].replace(",", "."))
            qty_unit = parts[1] if len(parts) > 1 else "unit"
        except ValueError:
            pass

    categories = product.get("categories_tags", [])
    category = categories[-1].replace("en:", "").replace("-", " ") if categories else ""
    result = {
        "sku": sku,
        "product_name": product.get("product_name") or "Unknown Product",
        "quantity": qty_value,
        "unit": qty_unit,
        "category": category,
        "brand": product.get("brands", ""),
        "image_url": product.get("image_url", ""),
        "raw_quantity": quantity_str,
        "updatedAt": datetime.now(timezone.utc),
    }

    try:
        get_db().collection("productLookups").document(sku).set(result, merge=True)
    except Exception as exc:
        logger.warning("[SKUClient] Lookup succeeded but Firestore cache failed: %s", exc)

    return result


def _quantity_from_lookup(data: dict) -> float:
    """Use package quantity when available, otherwise count one scanned item."""
    qty = data.get("quantity")
    try:
        if qty is not None and float(qty) > 0:
            return float(qty)
    except (TypeError, ValueError):
        pass
    return 1.0


def add_lookup_to_inventory(data: dict, source: str = "barcode-scan") -> dict:
    """
    Add a looked-up barcode item directly to Firestore inventory.

    If an in-stock pantry item already has the same barcode, this restocks that
    item by incrementing quantity/amount. Otherwise it creates a new pantry item.
    Always appends a usageLogs restocked event.
    """
    db = get_db()
    sku = str(data.get("sku", "")).strip()
    name = data.get("product_name") or "Unknown Product"
    unit = data.get("unit") or "unit"
    quantity_to_add = _quantity_from_lookup(data)
    now = datetime.now(timezone.utc)

    existing_docs = []
    if sku:
        existing_docs = list(
            db.collection(PANTRY_COLLECTION)
            .where("householdId", "==", HOUSEHOLD_ID)
            .where("barcode", "==", sku)
            .limit(1)
            .stream()
        )

    if existing_docs:
        doc = existing_docs[0]
        current = doc.to_dict() or {}
        current_qty = float(current.get("quantity", current.get("amount", 0)) or 0)
        new_qty = current_qty + quantity_to_add
        doc.reference.set(
            {
                "householdId": HOUSEHOLD_ID,
                "name": current.get("name") or name,
                "barcode": sku,
                "quantity": new_qty,
                "amount": new_qty,
                "unit": current.get("unit") or unit,
                "category": current.get("category") or data.get("category") or "misc",
                "brand": current.get("brand") or data.get("brand", ""),
                "image_url": current.get("image_url") or data.get("image_url", ""),
                "in_stock": True,
                "updatedAt": now,
                "source": current.get("source") or source,
            },
            merge=True,
        )
        item_id = doc.id
        action = "restocked"
    else:
        doc_ref = db.collection(PANTRY_COLLECTION).document()
        doc_ref.set(
            {
                "householdId": HOUSEHOLD_ID,
                "name": name,
                "barcode": sku,
                "quantity": quantity_to_add,
                "amount": quantity_to_add,
                "unit": unit,
                "category": data.get("category") or "misc",
                "brand": data.get("brand", ""),
                "image_url": data.get("image_url", ""),
                "expiryDate": None,
                "in_stock": True,
                "addedAt": now,
                "updatedAt": now,
                "source": source,
            }
        )
        item_id = doc_ref.id
        action = "created"

    db.collection(USAGE_LOGS_COLLECTION).document().set(
        {
            "householdId": HOUSEHOLD_ID,
            "item_id": item_id,
            "item_name": name,
            "sku": sku or None,
            "event_type": "restocked",
            "action_type": "restocked",
            "delta": quantity_to_add,
            "quantity_changed": quantity_to_add,
            "quantity_after": quantity_to_add if action == "created" else new_qty,
            "timestamp": now,
            "source": source,
        }
    )

    return {
        "status": "success",
        "action": action,
        "id": item_id,
        "sku": sku,
        "name": name,
        "quantity_added": quantity_to_add,
        "unit": unit,
    }


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
      1. Attempt Open Food Facts lookup and cache the result in Firestore.
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


def auto_add_sku_async(
    sku: str,
    on_success: Callable[[dict], None],
    on_error: Optional[Callable[[str], None]] = None,
    on_offline: Optional[Callable[[str], None]] = None,
) -> None:
    """
    Fire-and-forget barcode lookup plus inventory write.

    This is the scanner-first path: one scan ending in Enter looks up the UPC,
    adds or restocks the matching pantry item, logs the restock event, and then
    calls on_success on the Kivy main thread.
    """
    def _worker():
        try:
            lookup = _do_lookup(sku)
            result = add_lookup_to_inventory(lookup, source="kivy-barcode-scan")
            result["lookup"] = lookup
            logger.info("[SKUClient] ✅ Auto-added %s (%s)", result["name"], sku)
            Clock.schedule_once(lambda dt: on_success(result))

        except Exception as exc:
            error_str = str(exc)
            logger.error("[SKUClient] ❌ Auto-add failed for %s: %s", sku, error_str)
            is_network_error = _classify_network_error(exc)

            if is_network_error:
                _enqueue_scan(sku)
                msg = (
                    f"📶 Offline — '{sku}' saved locally. "
                    f"Will auto-add when connection is restored. "
                    f"({pending_scan_count()} scan(s) queued)"
                )
                callback = on_offline or on_error
                if callback:
                    Clock.schedule_once(lambda dt: callback(msg))
            elif on_error:
                Clock.schedule_once(lambda dt: on_error(error_str))

    t = threading.Thread(target=_worker, daemon=True, name=f"sku-auto-add-{sku[:8]}")
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
    when online, flushes pending SQLite scans to Open Food Facts/Firestore.

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
      2. If online: attempt to look up and auto-add each pending scan.
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
            lookup = _do_lookup(sku)
            add_lookup_to_inventory(lookup, source="kivy-offline-sync")
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
