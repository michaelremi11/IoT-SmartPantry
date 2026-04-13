# hub/scanner/discover_scanner.py
# Helper utility to identify the barcode scanner device path.

import evdev

def find_scanner():
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    print("Available Input Devices:")
    for device in devices:
        print(f"Path: {device.path} | Name: {device.name} | Phys: {device.phys}")
        # Look for keywords like 'Barcode', 'Symbol', 'Scanner', 'HID'
        if any(term in device.name.lower() or term in (device.phys or "").lower() 
                for term in ["barcode", "scanner", "symbol", "hid"]):
            print(f"  >>> Potential matches: {device.path}")

if __name__ == "__main__":
    try:
        find_scanner()
    except Exception as e:
        print(f"Error: {e}. Are you on Linux/Raspberry Pi?")
