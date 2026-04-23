"""
hub/ui/app.py
Root Kivy application for the Smart Pantry Hub.
Wires together:
  • ScreenManager + screens
  • KeyboardWedge barcode scanner (Window.bind)
  • Async FastAPI SKU lookup with SQLite offline fallback
  • Background sync monitor (re-syncs offline scans on reconnect)
  • RAM-Guard check before Ollama meal recommendations
  • Sense HAT environment logger
"""

import threading
import logging

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, SlideTransition
from kivy.clock import Clock

from hub.ui.screens import PantryScreen, AddItemScreen
from hub.scanner.keyboard_wedge import KeyboardWedge
from hub.services.sku_client import (
    lookup_sku_async,
    start_sync_monitor,
    stop_sync_monitor,
    pending_scan_count,
)
from hub.services.ram_guard import is_ram_ok, show_busy_warning
from hub.sensors import EnvironmentLogger

logger = logging.getLogger(__name__)


class SmartPantryApp(App):
    """Main Kivy application."""

    title = "Smart Pantry Hub"

    def build(self):
        # ── Screen manager ─────────────────────────────────────────────
        self.sm = ScreenManager(transition=SlideTransition())
        self.add_item_screen = AddItemScreen()
        self.pantry_screen   = PantryScreen()

        self.sm.add_widget(self.pantry_screen)
        self.sm.add_widget(self.add_item_screen)

        # ── Keyboard-wedge barcode scanner ─────────────────────────────
        self.wedge = KeyboardWedge(on_scan=self._on_barcode)
        self.wedge.attach()

        # ── Offline sync monitor ───────────────────────────────────────
        # Polls every 30 s; when Wi-Fi restores, flushes cached scans
        # to FastAPI and notifies the UI via _on_sync_complete().
        start_sync_monitor(on_sync=self._on_sync_complete)

        # ── Environment logger (background thread) ─────────────────────
        env_logger = EnvironmentLogger()
        env_thread = threading.Thread(target=env_logger.run_loop, daemon=True)
        env_thread.start()

        # Show pending offline scan count on startup (if any)
        pending = pending_scan_count()
        if pending > 0:
            logger.info("[App] %d offline scan(s) queued from previous session.", pending)
            Clock.schedule_once(
                lambda dt: self.pantry_screen.set_banner(
                    f"📶 {pending} offline scan(s) will sync when online.", level="warning"
                ),
                2.0,   # slight delay so the screen has finished rendering
            )

        return self.sm

    def on_stop(self):
        """Clean up scanner binding and sync monitor on exit."""
        self.wedge.detach()
        stop_sync_monitor()

    # ------------------------------------------------------------------
    # Scanner callback
    # ------------------------------------------------------------------

    def _on_barcode(self, sku: str):
        """
        Called on the Kivy main thread by KeyboardWedge when a full
        barcode is received.

        Steps:
          1. Navigate to add_item screen (immediate feedback).
          2. Fire async lookup → on success: auto-fill form fields.
             On network failure: save to SQLite cache, show offline notice.
        """
        logger.info("[App] Barcode received: %s", sku)

        def _switch_screen(*_):
            self.sm.current = "add_item"
            self.add_item_screen.prefill_barcode(sku)
            self.add_item_screen.set_status("🔍 Looking up product…", color="info")

        Clock.schedule_once(_switch_screen)

        lookup_sku_async(
            sku=sku,
            on_success=self._on_sku_found,
            on_error=self._on_sku_error,
            on_offline=self._on_sku_offline,
        )

    def _on_sku_found(self, data: dict):
        """Auto-fill the Add Item form with API-returned product data."""
        self.add_item_screen.prefill_from_api(data)
        self.add_item_screen.set_status(
            f"✅ Found: {data.get('product_name', 'Unknown')}", color="success"
        )

    def _on_sku_error(self, error: str):
        """API reachable but product not found (404) or server error."""
        logger.warning("[App] SKU lookup error: %s", error)
        self.add_item_screen.set_status(
            "⚠️ Product not found — fill in manually.", color="warning"
        )

    def _on_sku_offline(self, message: str):
        """Network unavailable; scan was saved to SQLite cache."""
        logger.info("[App] Offline scan queued: %s", message)
        self.add_item_screen.set_status(message, color="warning")

    # ------------------------------------------------------------------
    # Sync monitor callback
    # ------------------------------------------------------------------

    def _on_sync_complete(self, n_synced: int):
        """Called by sync monitor when offline scans have been flushed."""
        logger.info("[App] ✅ %d offline scan(s) synced.", n_synced)
        self.add_item_screen.set_status(
            f"📡 Back online — {n_synced} queued scan(s) synced!", color="success"
        )

    # ------------------------------------------------------------------
    # Meal recommendations (RAM-guarded)
    # ------------------------------------------------------------------

    def request_meal_recommendations(self):
        """
        Trigger an Ollama meal recommendation request if RAM is adequate.
        Call this from the PantryScreen 'Meal Ideas' button.
        """
        if not is_ram_ok():
            show_busy_warning(app=self)
            return

        from hub.services.meal_recommender import get_meal_recommendations

        def _worker():
            try:
                recipes = get_meal_recommendations()
                Clock.schedule_once(lambda dt: self._on_recipes_ready(recipes))
            except Exception as exc:
                logger.error("[App] Meal recommendations failed: %s", exc)
                Clock.schedule_once(
                    lambda dt: self.pantry_screen.set_banner(
                        "❌ Could not generate meal ideas. Check Ollama is running.",
                        level="error",
                    )
                )

        threading.Thread(target=_worker, daemon=True, name="meal-rec").start()

    def _on_recipes_ready(self, recipes: list[dict]):
        """Deliver recipe results to the UI (already on main thread via Clock)."""
        if hasattr(self.pantry_screen, "show_recipes"):
            self.pantry_screen.show_recipes(recipes)
        else:
            # Fallback: log recipes until the recipes UI widget is built
            for r in recipes:
                logger.info("[App] 🍽️  %s (%s min, %s)", r.get("name"), r.get("time_minutes"), r.get("difficulty"))


def run():
    SmartPantryApp().run()
