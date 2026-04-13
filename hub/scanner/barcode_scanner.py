"""
hub/scanner/barcode_scanner.py
Placeholder handler for a USB HID barcode scanner.

Most USB barcode scanners enumerate as a standard keyboard device.
On Linux (Raspberry Pi), we use `evdev` to listen for HID key events
and assemble barcode strings without interfering with the Kivy UI.

TODO:
  1. Install: pip install evdev
  2. Find your scanner device: python -m evdev.evtest
  3. Replace SCANNER_DEVICE_PATH with the correct /dev/input/eventX path.
"""

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Path to the USB barcode scanner's event device.
# Run `python -m evdev.evtest` on the Pi to discover the correct path.
SCANNER_DEVICE_PATH = "/dev/input/event0"  # TODO: update this

# Key code → character mapping (subset for barcode digits)
_KEY_MAP = {
    "KEY_0": "0", "KEY_1": "1", "KEY_2": "2", "KEY_3": "3",
    "KEY_4": "4", "KEY_5": "5", "KEY_6": "6", "KEY_7": "7",
    "KEY_8": "8", "KEY_9": "9",
    "KEY_A": "A", "KEY_B": "B", "KEY_C": "C", "KEY_D": "D",
    "KEY_E": "E", "KEY_F": "F",
}


class BarcodeScanner:
    """
    Listens for USB HID barcode scanner input via evdev.
    Calls `on_scan(barcode: str)` when a full barcode is received
    (terminated by KEY_ENTER from the scanner).
    """

    def __init__(self, on_scan: Callable[[str], None], device_path: str = SCANNER_DEVICE_PATH):
        self.on_scan = on_scan
        self.device_path = device_path
        self._buffer: list[str] = []
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """Start listening for barcode events in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        logger.info(f"[Scanner] Listening on {self.device_path}")

    def stop(self):
        """Stop the background listener."""
        self._running = False

    def _listen(self):
        try:
            import evdev
            device = evdev.InputDevice(self.device_path)
            for event in device.read_loop():
                if not self._running:
                    break
                if event.type == evdev.ecodes.EV_KEY:
                    key_event = evdev.categorize(event)
                    if key_event.keystate == evdev.KeyEvent.key_down:
                        key_name = key_event.keycode
                        if key_name == "KEY_ENTER":
                            barcode = "".join(self._buffer).strip()
                            self._buffer.clear()
                            if barcode:
                                logger.info(f"[Scanner] Scanned: {barcode}")
                                self.on_scan(barcode)
                        elif key_name in _KEY_MAP:
                            self._buffer.append(_KEY_MAP[key_name])
        except ImportError:
            logger.warning(
                "[Scanner] evdev not available. "
                "Scanner input is disabled (running in dev mode)."
            )
        except Exception as exc:
            logger.error(f"[Scanner] Error reading device: {exc}")
