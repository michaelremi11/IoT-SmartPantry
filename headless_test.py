import requests
import time
import json

BASE_URL = "http://localhost:8000"

print("--- Starting Headless Test ---")

# 1. Add Item
print("\n[1] Adding item to inventory...")
add_res = requests.post(f"{BASE_URL}/inventory", json={
    "name": "Test Avocado",
    "amount": 2.0,
    "quantity": 2.0,
    "category": "produce",
    "unit": "count",
    "in_stock": True,
    "expiryDate": None
})
print("Add status:", add_res.status_code)
add_data = add_res.json()
item_id = add_data.get("id")
print("Added Item ID:", item_id)

time.sleep(1)

# 2. Add Mock Recipe with the ingredient to Firebase so we can "Cook" it
print("\n[2] Skipping mock recipe generation, going directly to inventory deduction (which Cook does behind the scenes, but wait, cook_recipe needs a recipe ID).")
# If cook_recipe needs a recipe, let's create a recipe via direct firestore call or just test the action endpoint
print("Testing /inventory/action endpoint (Discard)...")
action_res = requests.post(f"{BASE_URL}/inventory/action", json={
    "item_id": item_id,
    "action_type": "discarded"
})
print("Discard status:", action_res.status_code)
print("Discard body:", action_res.json())

print("\n--- Test Complete ---")
