"""
hub/scanner/keyboard_wedge.py
Kivy-native keyboard wedge handler for USB barcode scanners.

USB barcode scanners in 'Keyboard Wedge' mode enumerate as a standard
USB HID keyboard and inject keystrokes into the OS. Kivy sees these
exactly like regular keyboard events via Window.bind(on_key_down=...).

Strategy
--------
  - Buffer every printable character the scanner sends.
  - Flush the buffer (emit the barcode) when KEY_ENTER is received.
  - Guard against false positives: a real barcode arrives in < 100 ms
    (scanners send characters back-to-back at ~1 ms per char).
    A human typing cannot match that speed. We use a timing gate
    (SCAN_TIMEOUT_S) to auto-flush stale buffers from manual typing.

Integration
-----------
  Instantiate `KeyboardWedge` in your Kivy App.build() and call
  `wedge.attach()`.  Call `wedge.detach()` in App.on_stop().

  Example::

      from hub.scanner.keyboard_wedge import KeyboardWedge

      class SmartPantryApp(App):
          def build(self):
              self.wedge = KeyboardWedge(on_scan=self._on_barcode)
              self.wedge.attach()
              return self.sm

          def on_stop(self):
              self.wedge.detach()

          def _on_barcode(self, sku: str):
              # sku is already stripped; send it to the FastAPI brain
              ...
"""

import logging
import time
from typing import Callable

from kivy.core.window import Window
from kivy.clock import Clock

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

# Maximum gap (seconds) between characters before the buffer is discarded.
# Scanners fire chars in < 2 ms each; humans type > 150 ms between keys.
SCAN_TIMEOUT_S: float = 0.08  # 80 ms

# Minimum barcode length to accept (avoids single-keystroke accidents).
MIN_BARCODE_LEN: int = 4

# Kivy keycode for Enter (both main and numpad)
_ENTER_KEYCODES = {13, 271}  # 13 = Return, 271 = KP_Enter

# Kivy printable key range (space=32 … ~=126)
_PRINTABLE_START = 32
_PRINTABLE_END   = 126


class KeyboardWedge:
    """
    Listens to Kivy's global key events and reconstructs the barcode
    string emitted by a USB HID scanner operating in keyboard-wedge mode.

    Parameters
    ----------
    on_scan : Callable[[str], None]
        Callback invoked on the **Kivy main thread** with the completed
        barcode / SKU string.
    scan_timeout_s : float
        Max inter-character gap before the buffer is reset (default 80 ms).
    min_len : int
        Minimum accepted barcode length (default 4).
    """

    def __init__(
        self,
        on_scan: Callable[[str], None],
        scan_timeout_s: float = SCAN_TIMEOUT_S,
        min_len: int = MIN_BARCODE_LEN,
    ):
        self.on_scan = on_scan
        self.scan_timeout_s = scan_timeout_s
        self.min_len = min_len

        self._buffer: list[str] = []
        self._last_key_time: float = 0.0
        self._timeout_event = None   # Kivy ClockEvent for auto-flush

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def attach(self):
        """Bind to Kivy's Window key events. Call once after Window exists."""
        Window.bind(on_key_down=self._on_key_down)
        logger.info("[KeyboardWedge] Attached to Kivy Window — scanner ready.")

    def detach(self):
        """Unbind from Kivy's Window. Call in App.on_stop()."""
        Window.unbind(on_key_down=self._on_key_down)
        self._cancel_timeout()
        logger.info("[KeyboardWedge] Detached from Kivy Window.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_key_down(self, window, keycode: int, scancode, codepoint, modifiers):
        """
        Kivy calls this for every key-down event.

        Parameters (Kivy convention)
        ----------------------------
        keycode   : int  — Unicode code point of the key
        codepoint : str  — printable character (may be None for special keys)
        modifiers : list — active modifier keys (shift, ctrl, …)
        """
        now = time.monotonic()

        # ── Timeout guard ──────────────────────────────────────────────
        if self._buffer and (now - self._last_key_time) > self.scan_timeout_s:
            logger.debug(
                "[KeyboardWedge] Timeout; discarding stale buffer: %r",
                "".join(self._buffer),
            )
            self._buffer.clear()
            self._cancel_timeout()

        self._last_key_time = now

        # ── Enter → flush ──────────────────────────────────────────────
        if keycode in _ENTER_KEYCODES:
            self._flush()
            return True   # consume the event so Kivy text inputs don't get a newline

        # ── Printable character → buffer ───────────────────────────────
        if codepoint and len(codepoint) == 1:
            char_code = ord(codepoint)
            if _PRINTABLE_START <= char_code <= _PRINTABLE_END:
                self._buffer.append(codepoint)
                self._reschedule_timeout()

        # Do NOT consume the event — let Kivy route it to focused widgets too
        return False

    def _flush(self):
        """Emit the buffered string if it meets minimum length."""
        self._cancel_timeout()
        barcode = "".join(self._buffer).strip()
        self._buffer.clear()

        if len(barcode) < self.min_len:
            logger.debug("[KeyboardWedge] Ignoring short sequence: %r", barcode)
            return

        logger.info("[KeyboardWedge] ✅ Scanned SKU: %s", barcode)

        # Invoke on_scan on the main thread (we're already on it via Window events)
        self.on_scan(barcode)

    def _reschedule_timeout(self):
        """Reset the auto-flush timer each time a character arrives."""
        self._cancel_timeout()
        self._timeout_event = Clock.schedule_once(
            lambda dt: self._auto_flush(), self.scan_timeout_s * 2
        )

    def _cancel_timeout(self):
        if self._timeout_event is not None:
            self._timeout_event.cancel()
            self._timeout_event = None

    def _auto_flush(self):
        """Called by Clock if no Enter arrives; discards incomplete barcode."""
        if self._buffer:
            logger.debug(
                "[KeyboardWedge] Auto-flush timeout; discarding: %r",
                "".join(self._buffer),
            )
            self._buffer.clear()
