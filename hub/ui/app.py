"""
hub/ui/app.py
Root Kivy application for the Smart Pantry Hub.
Wires together the ScreenManager, FirebaseDB, and barcode scanner.
"""

import threading
import logging

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, SlideTransition

from hub.firebase import get_db
from hub.ui.screens import PantryScreen, AddItemScreen
from hub.scanner import BarcodeScanner
from hub.sensors import EnvironmentLogger

logger = logging.getLogger(__name__)


class SmartPantryApp(App):
    """Main Kivy application."""

    title = "Smart Pantry Hub"

    def build(self):
        self.db = get_db()

        # Screen manager
        self.sm = ScreenManager(transition=SlideTransition())
        self.add_item_screen = AddItemScreen(db=self.db)
        self.pantry_screen = PantryScreen(db=self.db)

        self.sm.add_widget(self.pantry_screen)
        self.sm.add_widget(self.add_item_screen)

        # Barcode scanner (background thread)
        self.scanner = BarcodeScanner(on_scan=self._on_barcode)
        self.scanner.start()

        # Environment logger (background thread)
        env_logger = EnvironmentLogger(db=self.db)
        env_thread = threading.Thread(target=env_logger.run_loop, daemon=True)
        env_thread.start()

        return self.sm

    def _on_barcode(self, barcode: str):
        """Called from scanner background thread when a barcode is read."""
        from kivy.clock import Clock
        # Safely switch to add-item screen on the main thread
        def _switch(*_):
            self.sm.current = "add_item"
            self.add_item_screen.prefill_barcode(barcode)
        Clock.schedule_once(_switch)


def run():
    SmartPantryApp().run()
