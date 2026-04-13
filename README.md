# Smart Pantry + Kitchen Hub 🥦🧠

> **Reducing food waste. Tracking kitchen trends. One pantry at a time.**

---

## Overview

Smart Pantry + Kitchen Hub is an IoT-driven system that connects your physical kitchen — via a Raspberry Pi 4 touchscreen terminal — to a cloud-synced dashboard and an intelligent analytics backend. The system helps households:

- 📦 **Track pantry inventory** in real time via barcode scanning and manual entry
- 🌡️ **Monitor environmental conditions** (temperature, humidity) using the Sense HAT
- 🛒 **Manage shopping lists** that auto-populate based on consumption patterns
- 📊 **Forecast when items run low** using time-series consumption rate analytics
- ⚠️ **Flag kitchen anomalies** such as temperature spikes or humidity drops
- 🌍 **Reduce food waste** by surfacing expiry-driven "use soon" recommendations

---

## Architecture

```
IoT-SmartPantry/
│
├── hub/                  # Raspberry Pi 4 (Python + Kivy UI)
│   ├── firebase/         # Firebase Admin SDK init
│   ├── ui/               # Kivy touchscreen CRUD screens
│   ├── sensors/          # Sense HAT temp/humidity logging
│   └── scanner/          # USB barcode scanner input handler
│
├── web/                  # Next.js remote dashboard
│   ├── src/
│   │   ├── lib/          # Firebase client SDK init
│   │   └── app/          # App Router pages (inventory, shopping)
│   └── .env.local        # Web-specific Firebase env vars
│
├── analytics/            # Python FastAPI analytics microservice
│   ├── firebase/         # Firebase Admin SDK init
│   ├── models/           # Consumption rate & forecasting logic
│   └── main.py           # FastAPI entry point
│
├── .env.example          # Template for all Firebase credentials
└── README.md
```

---

## Tech Stack

| Layer       | Technology                              |
|-------------|------------------------------------------|
| Hub UI      | Python 3.11+, Kivy, Firebase Admin SDK  |
| Sensors     | Raspberry Pi Sense HAT, RPi.GPIO        |
| Barcode     | USB HID scanner (evdev / pynput)        |
| Cloud DB    | Firebase Firestore                      |
| Auth        | Firebase Authentication                 |
| Web         | Next.js 14, Firebase JS SDK v10         |
| Analytics   | Python FastAPI, Pandas, Firebase Admin  |

---

## Getting Started

### Prerequisites
- Raspberry Pi 4 (4GB RAM recommended) with Raspbian OS
- Sense HAT attached
- USB barcode scanner
- Firebase project created in the Firebase Console
- Node.js 18+ (for web dashboard)
- Python 3.11+ (for hub & analytics)

### 1. Clone and configure
```bash
git clone https://github.com/your-org/IoT-SmartPantry.git
cd IoT-SmartPantry
cp .env.example .env
# Fill in your Firebase credentials in .env
```

### 2. Hub (Raspberry Pi)
```bash
cd hub
pip install -r requirements.txt
python main.py
```

### 3. Web Dashboard
```bash
cd web
cp ../.env.example .env.local   # adjust NEXT_PUBLIC_ vars
npm install
npm run dev
```

### 4. Analytics Service
```bash
cd analytics
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

---

## Firebase Setup

See the **Firebase Console Checklist** section in the project documentation or run:
```
# Generated checklist is in docs/firebase-checklist.md
```

---

## Firestore Data Model

### `pantryItems/{itemId}`
```json
{
  "name": "Oat Milk",
  "barcode": "012345678901",
  "quantity": 2,
  "unit": "carton",
  "expiryDate": "2024-08-15",
  "category": "dairy-alternative",
  "addedAt": "<timestamp>",
  "updatedAt": "<timestamp>"
}
```

### `shoppingList/{itemId}`
```json
{
  "name": "Oat Milk",
  "quantity": 1,
  "addedBy": "analytics-auto",
  "addedAt": "<timestamp>",
  "checked": false
}
```

### `environmentLogs/{logId}`
```json
{
  "deviceId": "hub-rpi4-001",
  "temperatureC": 22.4,
  "humidityPercent": 55.2,
  "timestamp": "<timestamp>"
}
```

---

## Goals

1. **Reduce Food Waste**: Expiry tracking and "use soon" nudges prevent items from spoiling unnoticed.
2. **Automate Replenishment**: Consumption-rate analytics trigger shopping list additions before you run out.
3. **Kitchen Awareness**: Environmental logging catches fridge/freezer issues before food spoils.
4. **Family-Friendly**: Touchscreen UI on the hub requires no smartphone; anyone in the household can update inventory.

---

## License

MIT — see [LICENSE](LICENSE)
