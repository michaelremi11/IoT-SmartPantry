"""
hub/ui/screens/pantry_screen.py
Kivy screen for viewing and managing pantry inventory.
"""

from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.clock import Clock


class PantryScreen(Screen):
    """
    Displays the current pantry inventory pulled from Firestore.
    Supports Add, Edit, and Delete operations via touchscreen.
    """

    def __init__(self, db, **kwargs):
        super().__init__(**kwargs)
        self.db = db
        self.name = "pantry"
        self._build_ui()
        # Refresh inventory every 30 seconds
        Clock.schedule_interval(self._refresh, 30)

    def _build_ui(self):
        root = BoxLayout(orientation="vertical", padding=16, spacing=10)

        # Header
        header = BoxLayout(size_hint_y=None, height=60, spacing=10)
        header.add_widget(
            Label(
                text="🥦 Pantry Inventory",
                font_size="22sp",
                bold=True,
                color=(0.2, 0.8, 0.4, 1),
            )
        )
        add_btn = Button(
            text="+ Add Item",
            size_hint_x=None,
            width=140,
            background_color=(0.2, 0.6, 1, 1),
        )
        add_btn.bind(on_press=self._on_add)
        header.add_widget(add_btn)
        root.add_widget(header)

        # Scrollable item list
        scroll = ScrollView()
        self.item_grid = GridLayout(
            cols=4,
            spacing=8,
            size_hint_y=None,
        )
        self.item_grid.bind(minimum_height=self.item_grid.setter("height"))

        # Column headers
        for col in ("Name", "Qty", "Expires", "Actions"):
            self.item_grid.add_widget(
                Label(text=col, bold=True, color=(0.7, 0.7, 0.7, 1))
            )

        scroll.add_widget(self.item_grid)
        root.add_widget(scroll)

        self.add_widget(root)
        self._refresh()

    def _refresh(self, *_args):
        """Pull the latest inventory from Firestore and repopulate the grid."""
        # Remove all rows below the header (first 4 widgets)
        header_widgets = list(self.item_grid.children)[-4:]
        self.item_grid.clear_widgets()
        for w in reversed(header_widgets):
            self.item_grid.add_widget(w)

        try:
            docs = self.db.collection("pantryItems").order_by("name").stream()
            for doc in docs:
                item = doc.to_dict()
                item["_id"] = doc.id
                self._add_row(item)
        except Exception as exc:
            self.item_grid.add_widget(
                Label(text=f"Error loading: {exc}", color=(1, 0.3, 0.3, 1))
            )

    def _add_row(self, item: dict):
        self.item_grid.add_widget(Label(text=item.get("name", "—")))
        self.item_grid.add_widget(
            Label(text=f"{item.get('quantity', 0)} {item.get('unit', '')}")
        )
        self.item_grid.add_widget(
            Label(text=item.get("expiryDate", "N/A"))
        )
        del_btn = Button(
            text="Delete",
            size_hint_y=None,
            height=40,
            background_color=(1, 0.3, 0.3, 1),
        )
        del_btn.bind(on_press=lambda _b, doc_id=item["_id"]: self._on_delete(doc_id))
        self.item_grid.add_widget(del_btn)

    def _on_add(self, *_args):
        """Navigate to the add-item form screen."""
        self.manager.current = "add_item"

    def _on_delete(self, doc_id: str):
        """Delete an item from Firestore and refresh."""
        try:
            self.db.collection("pantryItems").document(doc_id).delete()
            self._refresh()
        except Exception as exc:
            print(f"[PantryScreen] Delete error: {exc}")
