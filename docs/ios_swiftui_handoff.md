# Smart Pantry iOS SwiftUI Handoff

This document is the current handoff reference for building a native iOS app for Smart Pantry.

It supersedes older architecture notes where they conflict, especially older references to `analyticsEvents` and older compatibility APIs. The live app architecture now centers on:

- Firebase Auth for sign-in
- Firestore for app state
- direct client reads/writes for normal CRUD
- a background analytics worker that reads/writes Firestore
- household-scoped data isolation

## 1. Current Architecture

### Source of truth

The app is no longer server-first.

- Web clients talk directly to Firebase
- The future iOS client should also talk directly to Firebase
- The analytics worker does the heavy lifting and writes results back into Firestore
- The old FastAPI services exist for diagnostics and compatibility only

### Important rule for the iOS app

The iOS app should **not** depend on:

- Firebase Admin credentials
- service account keys
- the internal FastAPI endpoints for normal app behavior
- any compatibility API as the main app data path

For normal app functionality, the iOS app should:

- authenticate with Firebase Auth
- read/write Firestore directly
- create worker request documents in Firestore
- subscribe to worker-written summary documents in Firestore

## 2. Auth and Household Model

The system is built around **households**, not just individual users.

### Collections involved

- `users/{uid}`
- `households/{householdId}`

### Web behavior today

When a user signs up:

1. Firebase Auth account is created
2. a new `households/{householdId}` document is created
3. a `users/{uid}` document is created pointing to that household

### Current document shapes

#### `users/{uid}`

```json
{
  "uid": "firebase_uid",
  "email": "user@example.com",
  "displayName": "Luke",
  "householdId": "abc123",
  "householdName": "Luke Pantry",
  "createdAt": "<timestamp>",
  "updatedAt": "<timestamp>"
}
```

#### `households/{householdId}`

```json
{
  "name": "Luke Pantry",
  "ownerUid": "firebase_uid",
  "memberUids": ["firebase_uid"],
  "createdAt": "<timestamp>",
  "updatedAt": "<timestamp>"
}
```

### iOS requirement

The iOS app should reproduce the same flow:

- sign in with email/password
- create account with email/password
- on first account creation, create the household and user profile docs
- on sign in, load the `users/{uid}` doc and derive the active `householdId`

## 3. Core Firestore Collections the iOS App Must Use

All user-facing app data is scoped by `householdId`.

### `pantryItems`

Document fields used today:

```json
{
  "householdId": "abc123",
  "name": "Great Value Olive Oil",
  "barcode": "012345678905",
  "quantity": 16,
  "amount": 16,
  "unit": "fl oz",
  "category": "sauce",
  "brand": "Great Value",
  "image_url": "https://...",
  "expiryDate": "2026-05-15",
  "in_stock": true,
  "source": "web-dashboard",
  "addedAt": "<timestamp>",
  "updatedAt": "<timestamp>"
}
```

Notes:

- `quantity` is the primary quantity field
- `amount` is still written for backward compatibility and should stay mirrored to `quantity`
- `expiryDate` is a `YYYY-MM-DD` string, not a Firestore timestamp

### `shoppingList`

```json
{
  "householdId": "abc123",
  "name": "Milk",
  "quantity": 1,
  "unit": "unit",
  "category": "liquid",
  "barcode": "012345678905",
  "brand": "Great Value",
  "image_url": "https://...",
  "addedBy": "web-dashboard",
  "checked": false,
  "addedAt": "<timestamp>",
  "updatedAt": "<timestamp>"
}
```

Important current behavior:

- unchecked items are the active shopping list
- checking an item does **not** add it to pantry yet
- checked items remain on the list until the user clears them
- `Clear Purchased` adds checked items to pantry and deletes them from the list
- `Clear Entire List` clears all items, but first restocks pantry from checked items

### `recipes`

Recipes are worker-generated and household-scoped.

```json
{
  "householdId": "abc123",
  "title": "Creamy Chicken Pasta",
  "ingredients": [
    {
      "name": "chicken breast",
      "amount": 1,
      "unit": "unit",
      "canonical": "chicken breast",
      "family": "protein",
      "group": null,
      "optional": false,
      "display": "1 chicken breast"
    },
    {
      "name": "olive oil",
      "amount": 1,
      "unit": "tbsp",
      "canonical": "olive oil",
      "family": "oil",
      "group": "olive_oil",
      "optional": false,
      "display": "1 tbsp olive oil"
    }
  ],
  "instructions": "Step 1. Step 2. Step 3.",
  "source": "ai-generated",
  "estimated_time": "20 minutes",
  "created_at": "<timestamp>"
}
```

Notes:

- legacy string ingredients may still exist in some old docs, but the current direction is structured ingredient objects
- the iOS app should support both while preferring structured ingredients

### `usageLogs`

This is the analytics event log.

```json
{
  "householdId": "abc123",
  "item_id": "pantry_doc_id",
  "item_name": "Milk",
  "sku": "012345678905",
  "event_type": "restocked",
  "action_type": "restocked",
  "delta": 1,
  "quantity_changed": 1,
  "quantity_after": 2,
  "timestamp": "<timestamp>",
  "source": "web-dashboard"
}
```

Important notes:

- analytics are primarily driven off `usageLogs`
- `delta` is the real quantity change and should be correct
- `quantity_changed` still exists for compatibility and should usually mirror `delta`

### Worker request collections

#### `recipeRequests`

Clients write request documents here instead of calling a recipe API.

```json
{
  "householdId": "abc123",
  "type": "discover",
  "status": "pending",
  "createdBy": "ios-app",
  "createdAt": "<timestamp>"
}
```

#### `smartPlanRequests`

```json
{
  "householdId": "abc123",
  "status": "pending",
  "createdBy": "ios-app",
  "createdAt": "<timestamp>"
}
```

The app should then subscribe to the request doc and react to:

- `pending`
- `processing`
- `complete`
- `error`

### Worker output collections

#### `analyticsSummaries`

The worker writes summary documents using this ID convention:

- `{householdId}_sustainability`
- `{householdId}_wasteReport`
- `{householdId}_historicalSustainability`
- `{householdId}_popularCategories`
- `{householdId}_missions`
- `{householdId}_liveStatus`
- `{householdId}_liveTrend`
- `{householdId}_risk`
- `{householdId}_recipeUnlocks`
- `{householdId}_buySignals`

The client reads these docs only.

#### `smartShoppingPlans`

The worker keeps the latest plan at:

- `{householdId}_current`

The client reads this doc only.

### `productLookups`

This is a cache of UPC metadata.

The iOS app may:

- look up UPC data directly from Open Food Facts
- optionally try to write the lookup result to Firestore

But it must tolerate cache writes failing, because security rules may reserve write access to trusted server-side code.

## 4. Current User-Facing Features

The iOS app should aim for parity with the current useful web workflows.

### A. Auth

- sign in
- create account
- household bootstrap on signup
- sign out

### B. Pantry

- real-time pantry list
- search pantry items
- add pantry item manually
- barcode scan to auto-add pantry item
- cook item manually
- discard item manually
- delete depleted items when quantity reaches zero

### C. Recipes

- subscribe to real-time recipe list
- request recipe discovery by creating `recipeRequests`
- show recipe availability against pantry
- show missing ingredients
- cook a recipe and deduct pantry ingredients
- remove one recipe
- clear all recipes

### D. Shopping

- subscribe to real-time shopping list
- add shopping item manually
- barcode scan to add shopping item
- toggle checked state
- clear purchased items
- clear entire list
- request smart shopping plan
- subscribe to current smart shopping plan
- add smart-plan suggestions into shopping list

### E. Analytics

- sustainability summary
- waste report
- historical sustainability trend
- popular categories
- missions
- recipe unlocks
- buy signals
- live status
- live trend
- environment risk

## 5. Important Behavioral Rules

### Household scoping

Every pantry, shopping, recipe, usage-log, request, and summary interaction must be scoped to the currently signed-in user's `householdId`.

Do not build any global query that omits `householdId`.

### Shopping list checked-item behavior

Do not add checked shopping items into pantry immediately.

Current correct behavior is:

1. user checks the item
2. item stays on the shopping list
3. when user clears purchased items, then pantry is restocked and checked rows are removed

### Worker interaction

The iOS app should not try to generate recipes or smart plans itself.

It should:

- write request docs
- subscribe to request status
- subscribe to worker output docs

### UPC lookup behavior

For barcode scans:

1. read UPC from the camera scanner
2. fetch metadata from Open Food Facts
3. add/increment pantry or shopping item
4. best-effort cache the lookup if allowed

### Recipe quantity behavior

The current app now cares about amounts and units more than before.

When cooking a recipe:

- confirm enough quantity exists across matching pantry items
- allow grouped matching, not just exact string matching
- deduct quantities across multiple matching pantry items if needed

### Ingredient matching

The current web logic uses normalization plus grouped families.

Examples:

- `Great Value Olive Oil` should satisfy `olive oil`
- `olive oil` and `Olive Oil` should match
- pasta is grouped by subtype, not flattened entirely
  - `spaghetti`, `linguine` -> `long_pasta`
  - `penne`, `rotini` -> `shaped_pasta`

If the iOS app initially reads recipe availability only, that matching logic should be ported carefully rather than simplified to naive string contains.

## 6. Security and Privacy Requirements

### Must do

- use Firebase Auth client SDK
- use Firestore client SDK
- rely on Firebase security rules for end-user access
- keep all app data household-scoped
- store no service-account key in the app
- do not embed internal API tokens in the app

### Must not do

- do not use Firebase Admin SDK in iOS
- do not call protected compatibility/diagnostic APIs as the primary app path
- do not hardcode secrets in Swift files

### Current backend reality

The old compatibility FastAPI endpoints are now treated as internal services and protected by an API key. The iOS app should not be built on top of them.

## 7. Recommended SwiftUI App Structure

Suggested module structure:

- `App/`
- `Core/`
- `Features/Auth/`
- `Features/Pantry/`
- `Features/Shopping/`
- `Features/Recipes/`
- `Features/Analytics/`
- `Models/`
- `Services/`
- `Utilities/`

Suggested major services:

- `AuthService`
- `SessionStore`
- `FirestorePantryService`
- `FirestoreShoppingService`
- `FirestoreRecipeService`
- `FirestoreAnalyticsService`
- `UPCService`

Suggested state pattern:

- SwiftUI + `ObservableObject` / `@StateObject`
- view models per screen
- async/await for one-shot operations
- snapshot listeners for live collections and summary docs

## 8. Recommended V1 Screen Map

Use a `TabView` with something like:

- Pantry
- Shopping
- Recipes
- Analytics
- Account

### Pantry tab

- search bar
- pantry list
- manual add form
- barcode scan entry point
- quick actions: cooked / discarded

### Shopping tab

- shopping list
- manual add
- barcode scan
- checked item toggle
- clear purchased
- clear entire list
- smart shopping plan section

### Recipes tab

- recipe list
- discover button
- recipe detail
- ingredient availability state
- cook button
- remove recipe
- clear all recipes

### Analytics tab

- summary cards
- waste list
- trend chart
- buy signals
- environment status/risk

### Account tab

- household name
- display name
- email
- sign out

## 9. Barcode Scanning Recommendation

On iOS, use a native camera barcode workflow.

Recommended approach:

- AVFoundation-based scanner
- UPC-A / EAN support
- on successful scan, dismiss scanner and run lookup flow

The scanner should support:

- pantry add mode
- shopping add mode

## 10. Implementation Phasing

Recommended order:

### Phase 1

- app scaffold
- Firebase setup
- auth flow
- session loading
- household bootstrap

### Phase 2

- pantry list subscription
- manual pantry add
- pantry actions
- shopping list subscription
- manual shopping add

### Phase 3

- barcode scan for pantry and shopping
- Open Food Facts lookup service
- duplicate/increment behavior

### Phase 4

- recipes
- recipe discovery requests
- recipe availability and cook flow

### Phase 5

- analytics summary screens
- smart shopping plan
- request status UX

### Phase 6

- polish
- error handling
- loading states
- accessibility
- test pass

## 11. Known Sharp Edges

- The older `docs/firestore_schema.md` contains stale references to `analyticsEvents`. The live analytics flow now depends on `usageLogs` and worker-written summaries.
- `productLookups` cache writes may fail from client code. That should not block barcode add flows.
- Some old recipe docs may still contain string ingredients. The iOS app should parse both string and structured forms.
- Compatibility APIs in `api/` are not the main architecture and should not drive app design.

## 12. What “Done” Looks Like

A good iOS V1 is done when:

- a user can sign up and create a household
- a returning user can sign in and load the correct household data
- pantry, shopping, and recipes are real-time and household-scoped
- barcode scanning works for pantry and shopping
- shopping checked items are only applied to pantry when cleared
- recipe discovery works via Firestore requests
- smart shopping plan works via Firestore requests
- analytics render from `analyticsSummaries`
- the app uses no server secrets and no internal API token

