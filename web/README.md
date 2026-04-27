# Smart Pantry Web Dashboard

This Next.js app talks directly to Firebase Firestore for normal application
state. It does not call the FastAPI backend for inventory, shopping list,
recipe discovery, smart shopping plans, or analytics reads.

## Setup

Create `web/.env.local` with the Firebase client variables from the root
`.env.example`:

```bash
NEXT_PUBLIC_FIREBASE_API_KEY=...
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=...
NEXT_PUBLIC_FIREBASE_PROJECT_ID=...
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=...
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=...
NEXT_PUBLIC_FIREBASE_APP_ID=...
NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID=...
```

Run the app:

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

The Firebase worker (`uvicorn analytics.main:app --port 8000`) should also be
running if you want generated recipes, refreshed analytics summary documents,
and smart shopping plans.

## Barcode Scanning

The inventory page has a Barcode Scanner field. A USB keyboard-wedge scanner
can type the UPC and its trailing Enter into this field; Enter submits the scan,
looks up the product through Open Food Facts, and adds/restocks the item in
Firestore without another click.

The shopping page has the same scanner pattern, but it adds/increments unchecked
`shoppingList` items instead of pantry stock. Checking off a shopping item
restocks the pantry using that item metadata.
