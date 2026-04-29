# Prompt for a New Chat: Build the Smart Pantry iOS App in SwiftUI

Use this prompt in a new chat that has access to this repository.

---

You are helping build a native iOS app for the Smart Pantry project.

I want you to work inside the existing repository and create a new SwiftUI-based iOS app that works with the current architecture.

Before you start coding, read these files first:

- `docs/ios_swiftui_handoff.md`
- `web/src/lib/auth.ts`
- `web/src/lib/firestore.ts`
- `firestore.rules`
- `analytics/worker.py`
- `analytics/services/firebase_analytics.py`

Then inspect the repository as needed and implement the iOS app.

## High-level goal

Build a native iOS app in SwiftUI that supports the same real user workflows as the current web app:

- Firebase email/password auth
- household-scoped pantry
- shopping list
- recipe discovery and recipe cooking
- analytics display
- barcode scanning

The iOS app must fit the current architecture:

- normal app data goes directly through Firebase
- the app should use Firebase Auth + Firestore client SDKs
- heavy lifting stays in the analytics worker
- the app should create Firestore request documents instead of calling a recipe/smart-plan API

## Important architectural constraints

1. Do not use Firebase Admin SDK in the iOS app.
2. Do not embed a service-account credential anywhere in the app.
3. Do not rely on the internal FastAPI compatibility endpoints for normal app use.
4. Do not embed the protected internal API token in the app.
5. All Firestore reads/writes must be scoped to the current user's `householdId`.
6. Keep existing backend behavior intact unless a change is truly required.

## Build expectations

Create a clean, professional native iOS app.

Use:

- SwiftUI
- Firebase Auth
- Firebase Firestore
- MVVM-style organization
- async/await where appropriate
- real-time snapshot listeners for live Firestore-backed screens
- AVFoundation or another appropriate native barcode scanning approach

## App scope

### Auth

Implement:

- sign in
- create account
- sign out
- bootstrap household and user docs on first signup
- load current session and household profile on app launch

Match the existing web logic for user/household creation.

### Pantry

Implement:

- subscribe to pantry items for the current household
- search pantry items
- add pantry items manually
- barcode scan to add pantry items
- cooked action
- discarded action

### Shopping

Implement:

- subscribe to shopping list for the current household
- add shopping items manually
- barcode scan to add shopping items
- toggle checked state
- clear purchased items
- clear entire list

Important: checking an item should not immediately add it to pantry. Restocking happens only when checked items are cleared.

### Recipes

Implement:

- subscribe to recipes for the current household
- request recipe discovery by writing a `recipeRequests` Firestore document
- subscribe to request status
- render recipe details
- show whether ingredients are available
- cook a recipe and deduct pantry items
- remove a recipe
- clear all recipes

The app should support the current structured ingredient model and tolerate old string-based recipe ingredients.

### Analytics

Implement read-only views for worker-generated Firestore summary docs:

- sustainability
- waste report
- historical sustainability
- popular categories
- missions
- recipe unlocks
- buy signals
- live status
- live trend
- environment risk

### Smart Shopping Plan

Implement:

- request smart shopping plan by writing a `smartPlanRequests` document
- subscribe to request status
- subscribe to the current `smartShoppingPlans/{householdId}_current` doc
- let the user add suggestions into the shopping list

### Barcode scanning

Implement camera-based barcode scanning for:

- pantry add flow
- shopping add flow

The mobile barcode flow should:

1. scan UPC/EAN
2. fetch metadata from Open Food Facts
3. add or increment the relevant Firestore document
4. optionally try to cache lookup metadata in `productLookups`
5. continue gracefully if cache write fails

## Data and Firestore requirements

Use the shapes and behaviors described in:

- `docs/ios_swiftui_handoff.md`
- `web/src/lib/firestore.ts`

Pay special attention to:

- `householdId` scoping
- `quantity` plus mirrored `amount`
- `usageLogs` writes for inventory-affecting actions
- request doc status flow
- recipe ingredient matching and quantity handling

## Matching and quantity behavior

Do not use naive string equality for recipe availability.

Port the current pantry/recipe matching ideas from the web app:

- normalized matching
- grouped families for ingredients like pasta and milk
- quantity-aware availability
- deduction across multiple pantry items if needed

Examples of intended behavior:

- `Great Value Olive Oil` should satisfy `olive oil`
- two compatible milk items should count together
- spaghetti and penne should not be treated as identical if the grouped subtype matters

## UX guidance

Use a practical native app structure, likely a `TabView`, with something close to:

- Pantry
- Shopping
- Recipes
- Analytics
- Account

The UI should feel like a real utility app, not a marketing site:

- dense but readable
- quick to scan
- clean empty states
- clear loading and error states
- solid handling of long-running worker requests

## Expected workflow

1. Inspect the repo and summarize the plan.
2. Scaffold the iOS app in this repository.
3. Wire up Firebase configuration.
4. Implement the app in phases, starting with auth and Firestore foundation.
5. Keep the user updated as you work.
6. Run whatever local verification you can.
7. At the end, explain exactly what was added, how to run the iOS app, and what remains.

## Deliverables

I expect:

- a native SwiftUI app added to this repo
- a clean project structure
- Firebase-backed auth and data flow
- barcode scanning
- recipe and shopping worker-request integration
- analytics screens backed by Firestore summaries
- clear run instructions

## Very important

Treat the current web app and worker behavior as the contract unless a better approach is clearly necessary.

If you find stale docs or outdated compatibility code, trust the current live architecture described in:

- `docs/ios_swiftui_handoff.md`
- `web/src/lib/auth.ts`
- `web/src/lib/firestore.ts`

Start by reading the handoff files and summarizing your build plan before making changes.

