# Smart Pantry + Kitchen Hub 🥦🧠

> **Reducing food waste. Tracking kitchen trends. One pantry at a time.**

---

## Overview

Smart Pantry + Kitchen Hub is an IoT-driven system that connects your physical kitchen — via a Raspberry Pi 4 touchscreen terminal — to Firebase-backed web/mobile clients and an intelligent background worker. The system helps households:

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
├── hub/                  # Raspberry Pi 4 (Python + Kivy UI, direct Firestore)
│   ├── firebase/         # Firebase Admin SDK init
│   ├── ui/               # Kivy touchscreen CRUD screens
│   ├── sensors/          # Sense HAT temp/humidity logging
│   └── scanner/          # USB barcode scanner input handler
│
├── web/                  # Next.js remote dashboard (direct Firebase client)
│   ├── src/
│   │   ├── lib/          # Firebase client SDK init
│   │   └── app/          # App Router pages (inventory, shopping)
│   └── .env.local        # Web-specific Firebase env vars
│
├── analytics/            # FastAPI diagnostics + Firebase worker
│   ├── firebase/         # Firebase Admin SDK init
│   ├── models/           # Consumption rate & forecasting logic
│   ├── services/         # Firebase-backed analytics builders
│   ├── worker.py         # Recipe/smart-plan request processor
│   └── main.py           # FastAPI entry point
│
├── api/                  # Legacy/compat FastAPI routes, Firestore-only
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
| Web         | Next.js 16, Firebase JS SDK             |
| Analytics   | Python FastAPI, Pandas, Firebase Admin  |

---

## Current Data Flow

```
Web / future mobile app / Pi hub
  ├─ read and write normal app state directly in Firestore
  └─ create request documents for heavy work

Firebase Firestore
  ├─ pantryItems, shoppingList, recipes
  ├─ usageLogs, environmentLogs
  ├─ recipeRequests, smartPlanRequests
  └─ analyticsSummaries, smartShoppingPlans

Firebase worker service
  ├─ polls pending request documents
  ├─ calls local Ollama for recipe generation
  ├─ computes analytics from Firestore
  └─ writes results back to Firestore
```

The web app no longer calls the backend for inventory, shopping list, cooking/discarding, recipe discovery, smart shopping plans, or analytics reads. It uses Firestore subscriptions and writes. The backend remains for background processing and optional diagnostic/compatibility HTTP endpoints.

---

## Barcode Auto-Add

USB barcode scanners that operate in keyboard-wedge mode are supported. The scanner sends the UPC followed by Enter.

- On the Pi hub, a scan is captured globally, looked up through Open Food Facts, and auto-added to Firestore.
- On the web inventory page, scan an item you physically have. It is added/restocked in `pantryItems`.
- On the web shopping page, scan an item you want to buy. It is added/incremented in `shoppingList`.
- If the UPC already exists in `pantryItems`, the scan restocks that item instead of creating a duplicate.
- If the UPC or normalized name already exists as an unchecked shopping item, the shopping scan/suggestion increments that item instead of creating a duplicate.
- Each successful scan writes a `usageLogs` restock event for analytics.
- UPC metadata is cached in `productLookups` when rules allow it.

Expiry dates are not available from UPC databases, so scanned items are added with `expiryDate: null` and can be edited later.

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

### 4. Firebase Worker / Analytics Service
```bash
cd analytics
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
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
  "comfort_score": 92,
  "timestamp": "<timestamp>"
}
```

### Worker-owned collections
- `usageLogs`: immutable restocked/cooked/discarded events used for sustainability, waste, and buy-signal analytics.
- `recipeRequests`: client-created `{ status: "pending" }` documents that the worker turns into saved `recipes`.
- `smartPlanRequests`: client-created pending documents that the worker turns into `smartShoppingPlans`.
- `analyticsSummaries`: worker-written dashboard docs such as `sustainability`, `wasteReport`, `popularCategories`, `missions`, `liveStatus`, and `risk`.
- `productLookups`: cached barcode metadata from Open Food Facts.

---

## Seed Analytics Test Data

If you want realistic demo data for one household without hand-entering weeks of inventory activity, use:

```bash
cd /Users/lukedotzler/Documents/IotProject/IoT-SmartPantry
python scripts/seed_household_analytics.py --household-id YOUR_HOUSEHOLD_ID --reset
```

What it seeds:

- `pantryItems`
- `usageLogs`
- `environmentLogs`
- `recipes`

Then it refreshes:

- `analyticsSummaries`
- `smartShoppingPlans`

Useful flags:

```bash
python scripts/seed_household_analytics.py --household-id YOUR_HOUSEHOLD_ID --dry-run
python scripts/seed_household_analytics.py --household-id YOUR_HOUSEHOLD_ID --scenario waste-heavy
python scripts/seed_household_analytics.py --household-id YOUR_HOUSEHOLD_ID --days 60
```

`--reset` only clears data for the specified household; it does not wipe the whole Firebase project.

---

## Goals

1. **Reduce Food Waste**: Expiry tracking and "use soon" nudges prevent items from spoiling unnoticed.
2. **Automate Replenishment**: Consumption-rate analytics trigger shopping list additions before you run out.
3. **Kitchen Awareness**: Environmental logging catches fridge/freezer issues before food spoils.
4. **Family-Friendly**: Touchscreen UI on the hub requires no smartphone; anyone in the household can update inventory.

---

## License

MIT — see [LICENSE](LICENSE)
