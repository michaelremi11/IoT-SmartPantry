"""
hub/services/ram_guard.py
RAM-Guard — monitors available system memory on the Raspberry Pi 4.

Two modes of operation
----------------------

1. **Sidecar / daemon mode** (CLI):
   Run by ollama_monitor.service as a background process.
   Polls /proc/meminfo every N seconds and writes a flag file:
     • /run/smart-pantry/ram_ok   → present when RAM is adequate
     • file absent (deleted)      → RAM is low; Ollama requests blocked

2. **Library mode** (imported by sku_client.py / meal_recommender.py):
   `is_ram_ok()`   — fast, non-blocking check of the flag file.
   `get_available_mb()` — returns current available RAM in MB directly
                          from /proc/meminfo (no flag file needed).

Integration with Kivy UI
------------------------
Call `is_ram_ok()` before dispatching an Ollama request.
If it returns False, call `show_busy_warning()` to display the
"System Busy" banner on the Kivy main thread instead.

    from hub.services.ram_guard import is_ram_ok, show_busy_warning

    if is_ram_ok():
        recipes = get_meal_recommendations(db)
    else:
        show_busy_warning()
"""

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (all overridable via env or CLI)
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLD_MB: int   = int(os.getenv("RAM_GUARD_THRESHOLD_MB", "500"))
DEFAULT_POLL_INTERVAL: int  = int(os.getenv("RAM_GUARD_POLL_INTERVAL", "10"))
DEFAULT_FLAG_FILE: str       = os.getenv(
    "RAM_GUARD_FLAG_FILE", "/run/smart-pantry/ram_ok"
)

# ---------------------------------------------------------------------------
# Core memory reader — uses /proc/meminfo for zero-dependency accuracy
# ---------------------------------------------------------------------------

def get_available_mb() -> float:
    """
    Read 'MemAvailable' from /proc/meminfo and return as MB.

    MemAvailable is the kernel's estimate of available RAM without swapping
    (introduced in Linux 3.14). It is the most accurate single metric for
    'can I start a heavy process?' decisions.

    Falls back to psutil if /proc/meminfo is unavailable (non-Linux dev env).
    """
    try:
        with open("/proc/meminfo", "r") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return kb / 1024
    except (FileNotFoundError, ValueError, IndexError):
        pass

    # Fallback: psutil (works on macOS/Windows for dev)
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 * 1024)
    except ImportError:
        logger.warning("[RAMGuard] Cannot read memory — assuming OK.")
        return float("inf")


# ---------------------------------------------------------------------------
# Flag-file API (fast path for library callers)
# ---------------------------------------------------------------------------

def is_ram_ok(flag_file: str = DEFAULT_FLAG_FILE) -> bool:
    """
    Return True if the RAM-guard flag file exists (RAM is adequate).

    This is a fast O(1) stat() call — safe to call from the Kivy main thread.
    If the flag file is missing (guard not running, or RAM low), returns True
    as a safe default so the app doesn't block all Ollama calls on first boot.
    """
    fp = Path(flag_file)
    if not fp.parent.exists():
        # Guard not yet started (e.g., development machine) — allow requests
        return True
    return fp.exists()


def _write_flag(flag_file: Path, available_mb: float, threshold_mb: int):
    """Create or remove the flag file based on available RAM."""
    flag_file.parent.mkdir(parents=True, exist_ok=True)
    if available_mb >= threshold_mb:
        if not flag_file.exists():
            flag_file.touch()
            logger.info(
                "[RAMGuard] ✅ RAM OK: %.0f MB available (threshold: %d MB) — flag SET",
                available_mb, threshold_mb,
            )
    else:
        if flag_file.exists():
            flag_file.unlink()
            logger.warning(
                "[RAMGuard] ⚠️  RAM LOW: %.0f MB available (threshold: %d MB) — flag CLEARED",
                available_mb, threshold_mb,
            )


# ---------------------------------------------------------------------------
# Kivy UI helper
# ---------------------------------------------------------------------------

def show_busy_warning(app=None):
    """
    Display a 'System Busy — Low RAM' warning in the Kivy UI.

    Must be called on the Kivy main thread, or via Clock.schedule_once.

    Parameters
    ----------
    app : SmartPantryApp instance (optional).  If None, tries to look it
          up via kivy.app.App.get_running_app().
    """
    try:
        from kivy.app import App
        from kivy.clock import Clock

        def _show(dt):
            running_app = app or App.get_running_app()
            if running_app is None:
                return
            # Prefer an existing add_item_screen status label
            screen = getattr(running_app, "add_item_screen", None)
            if screen and hasattr(screen, "set_status"):
                screen.set_status(
                    "🔴 System Busy — not enough RAM for Meal Recs. Try again shortly.",
                    color="error",
                )
            else:
                # Fall back to a standalone popup
                from kivy.uix.popup import Popup
                from kivy.uix.label import Label
                popup = Popup(
                    title="System Busy",
                    content=Label(
                        text="⚠️ Low RAM detected.\nMeal recommendations are temporarily disabled.\n\nPlease wait a moment and try again.",
                        halign="center",
                    ),
                    size_hint=(0.75, 0.4),
                )
                popup.open()

        Clock.schedule_once(_show)

    except ImportError:
        # Not running in Kivy context (e.g., CLI tool or tests)
        logger.warning("[RAMGuard] show_busy_warning: Kivy not available.")
        print("⚠️  System Busy: Available RAM below threshold. Ollama request blocked.")


# ---------------------------------------------------------------------------
# Daemon / sidecar mode
# ---------------------------------------------------------------------------

def run_daemon(threshold_mb: int, flag_file: str, poll_interval: int):
    """
    Main polling loop for sidecar/daemon mode.
    Updates the flag file every `poll_interval` seconds.
    Handles SIGTERM gracefully (cleans up flag file on exit).
    """
    fp = Path(flag_file)

    def _cleanup(signum, frame):
        logger.info("[RAMGuard] Received signal %d — cleaning up and exiting.", signum)
        if fp.exists():
            fp.unlink()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT,  _cleanup)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] ram-guard: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logger.info(
        "[RAMGuard] Starting daemon | threshold: %d MB | flag: %s | poll: %ds",
        threshold_mb, flag_file, poll_interval,
    )

    while True:
        available = get_available_mb()
        _write_flag(fp, available, threshold_mb)

        # Log current stats at INFO level every poll cycle
        logger.info(
            "[RAMGuard] Poll: %.0f MB available | Flag: %s",
            available, "SET ✅" if fp.exists() else "CLEARED ⚠️",
        )

        time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="RAM-Guard: monitors available RAM and writes a flag file."
    )
    parser.add_argument(
        "--threshold-mb", type=int, default=DEFAULT_THRESHOLD_MB,
        help=f"Available RAM threshold in MB (default: {DEFAULT_THRESHOLD_MB})",
    )
    parser.add_argument(
        "--flag-file", default=DEFAULT_FLAG_FILE,
        help=f"Path to the flag file (default: {DEFAULT_FLAG_FILE})",
    )
    parser.add_argument(
        "--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL,
        help=f"Seconds between RAM checks (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="One-shot check: print available RAM and exit (don't loop).",
    )
    args = parser.parse_args()

    if args.check:
        mb = get_available_mb()
        ok = mb >= args.threshold_mb
        status = "OK ✅" if ok else "LOW ⚠️"
        print(f"Available RAM: {mb:.0f} MB  |  Threshold: {args.threshold_mb} MB  |  Status: {status}")
        sys.exit(0 if ok else 1)

    run_daemon(args.threshold_mb, args.flag_file, args.poll_interval)


if __name__ == "__main__":
    main()
