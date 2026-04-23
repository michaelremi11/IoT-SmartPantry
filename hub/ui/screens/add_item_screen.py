"""
hub/ui/screens/add_item_screen.py
Kivy screen for adding or editing a pantry item.
Supports manual entry and barcode-scanner pre-fill.
"""

import uuid
from datetime import datetime, timezone

from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
import os
import httpx


class AddItemScreen(Screen):
    """Form screen to add a new pantry item to Firestore."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.api_url = os.getenv("API_URL", "http://127.0.0.1:8000")
        self.name = "add_item"
        self._build_ui()

    def _build_ui(self):
        root = BoxLayout(orientation="vertical", padding=24, spacing=14)

        root.add_widget(
            Label(
                text="Add Pantry Item",
                font_size="20sp",
                bold=True,
                color=(0.2, 0.8, 0.4, 1),
                size_hint_y=None,
                height=48,
            )
        )

        fields = [
            ("Item Name *", "name_input", "e.g. Oat Milk"),
            ("Barcode", "barcode_input", "Scan or type barcode"),
            ("Quantity *", "qty_input", "e.g. 2"),
            ("Unit", "unit_input", "e.g. carton, kg, pack"),
            ("Expiry Date (YYYY-MM-DD)", "expiry_input", "e.g. 2024-12-31"),
            ("Category", "category_input", "e.g. dairy-alternative"),
        ]

        for label_text, attr, hint in fields:
            root.add_widget(Label(text=label_text, size_hint_y=None, height=30))
            ti = TextInput(hint_text=hint, size_hint_y=None, height=44, multiline=False)
            setattr(self, attr, ti)
            root.add_widget(ti)

        btn_row = BoxLayout(size_hint_y=None, height=52, spacing=12)
        cancel_btn = Button(text="Cancel", background_color=(0.4, 0.4, 0.4, 1))
        cancel_btn.bind(on_press=self._on_cancel)
        save_btn = Button(text="Save", background_color=(0.2, 0.7, 0.4, 1))
        save_btn.bind(on_press=self._on_save)

        self.status_label = Label(text="", color=(1, 0.3, 0.3, 1), size_hint_y=None, height=32)

        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(save_btn)
        root.add_widget(self.status_label)
        root.add_widget(btn_row)

        self.add_widget(root)

    def prefill_barcode(self, barcode: str):
        """Pre-fill the barcode field when the scanner fires."""
        self.barcode_input.text = barcode

    def prefill_from_api(self, data: dict):
        """
        Populate form fields from the FastAPI /lookup/{sku} response.

        Expected keys (all optional):
          product_name, quantity, unit, category, expiry_date
        """
        if data.get("product_name"):
            self.name_input.text = data["product_name"]
        if data.get("quantity"):
            self.qty_input.text = str(data["quantity"])
        if data.get("unit"):
            self.unit_input.text = data["unit"]
        if data.get("category"):
            self.category_input.text = data["category"]
        if data.get("expiry_date"):
            self.expiry_input.text = data["expiry_date"]

    def set_status(self, message: str, color: str = "info"):
        """
        Display a status message below the form.

        color: 'info' | 'success' | 'warning' | 'error'
        """
        _colors = {
            "info":    (0.4, 0.8, 1.0, 1),
            "success": (0.2, 0.9, 0.4, 1),
            "warning": (1.0, 0.75, 0.2, 1),
            "error":   (1.0, 0.3,  0.3, 1),
        }
        self.status_label.color = _colors.get(color, _colors["info"])
        self.status_label.text  = message

    def _on_save(self, *_args):
        name = self.name_input.text.strip()
        qty_str = self.qty_input.text.strip()

        if not name:
            self.status_label.text = "Item name is required."
            return
        if not qty_str.replace(".", "").isdigit():
            self.status_label.text = "Quantity must be a number."
            return

        item = {
            "name": name,
            "barcode": self.barcode_input.text.strip(),
            "quantity": float(qty_str),
            "unit": self.unit_input.text.strip() or "unit",
            "expiryDate": self.expiry_input.text.strip(),
            "category": self.category_input.text.strip(),
            "addedAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
        }

        try:
            httpx.post(f"{self.api_url}/inventory", json={"name": item["name"], "amount": item["quantity"], "unit": item["unit"], "category": item["category"], "in_stock": True})
            self._clear_fields()
            self.manager.current = "pantry"
        except Exception as exc:
            self.status_label.text = f"Save failed: {exc}"

    def _on_cancel(self, *_args):
        self._clear_fields()
        self.manager.current = "pantry"

    def _clear_fields(self):
        for attr in ("name_input", "barcode_input", "qty_input",
                     "unit_input", "expiry_input", "category_input"):
            getattr(self, attr).text = ""
        self.status_label.text = ""
