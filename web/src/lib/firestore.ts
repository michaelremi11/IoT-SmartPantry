// web/src/lib/firestore.ts
// Helper functions for reading pantry and shopping list data from Firestore.

import {
  collection,
  addDoc,
  doc,
  getDoc,
  getDocs,
  onSnapshot,
  query,
  orderBy,
  where,
  limit,
  serverTimestamp,
  setDoc,
  updateDoc,
  writeBatch,
  Unsubscribe,
  QuerySnapshot,
} from "firebase/firestore";
import { db } from "./firebase";

export interface PantryItem {
  id: string;
  name: string;
  barcode?: string;
  quantity: number;
  amount?: number;
  unit: string;
  expiryDate?: string;
  category?: string;
  brand?: string;
  image_url?: string;
  in_stock?: boolean;
  source?: string;
  addedAt?: Date;
  updatedAt?: Date;
}

export interface ShoppingItem {
  id: string;
  name: string;
  quantity: number;
  unit?: string;
  category?: string;
  barcode?: string;
  brand?: string;
  image_url?: string;
  addedBy?: string;
  checked: boolean;
  addedAt?: Date;
  updatedAt?: Date;
}

export interface FirestoreTimestamp {
  seconds: number;
  nanoseconds?: number;
}

export interface SmartShoppingPlan {
  staples?: { item: string; reason: string }[];
  unlocks?: { item: string; reason: string }[];
  waste_prevention?: { item: string; reason: string }[];
  updatedAt?: unknown;
}

export interface ProductLookup {
  sku: string;
  product_name: string;
  quantity: number | null;
  unit: string;
  category: string;
  brand?: string;
  image_url?: string;
  raw_quantity?: string;
}

export type ShoppingAddSource = "web-dashboard" | "barcode-scan" | "analytics-auto";

function mapDoc<T>(snap: QuerySnapshot): T[] {
  return snap.docs.map((doc) => ({ id: doc.id, ...doc.data() } as T));
}

/** Subscribe to real-time pantry inventory updates. */
export function subscribePantry(
  callback: (items: PantryItem[]) => void
): Unsubscribe {
  const q = query(collection(db, "pantryItems"), orderBy("name"));
  return onSnapshot(q, (snap) => callback(mapDoc<PantryItem>(snap)));
}

export function subscribeShoppingList(
  callback: (items: ShoppingItem[]) => void
): Unsubscribe {
  const q = query(collection(db, "shoppingList"), orderBy("addedAt", "desc"));
  return onSnapshot(q, (snap) => callback(mapDoc<ShoppingItem>(snap)));
}

export interface RecipeItem {
  id?: string;
  title: string;
  ingredients: string[];
  instructions: string;
  source: string;
  estimated_time?: string;
  created_at?: FirestoreTimestamp;
}

/** Subscribe to real-time recipe updates. */
export function subscribeRecipes(
  callback: (items: RecipeItem[]) => void
): Unsubscribe {
  const q = query(collection(db, "recipes"));
  return onSnapshot(q, (snap) => callback(mapDoc<RecipeItem>(snap)));
}

/** Subscribe to a server-generated analytics summary document. */
export function subscribeAnalyticsSummary<T>(
  docId: string,
  callback: (data: T | null) => void
): Unsubscribe {
  return onSnapshot(doc(db, "analyticsSummaries", docId), (snap) => {
    callback(snap.exists() ? ({ id: snap.id, ...snap.data() } as unknown as T) : null);
  });
}

export function subscribeSmartShoppingPlan(
  callback: (plan: SmartShoppingPlan | null) => void
): Unsubscribe {
  return onSnapshot(doc(db, "smartShoppingPlans", "current"), (snap) => {
    callback(snap.exists() ? (snap.data() as SmartShoppingPlan) : null);
  });
}

export async function addPantryItem(input: {
  name: string;
  quantity: number;
  unit: string;
  category?: string;
  expiryDate?: string | null;
  barcode?: string;
  brand?: string;
  image_url?: string;
  source?: string;
}) {
  const quantity = Number.isFinite(input.quantity) ? input.quantity : 0;
  const docRef = await addDoc(collection(db, "pantryItems"), {
    name: input.name,
    barcode: input.barcode || "",
    quantity,
    amount: quantity,
    unit: input.unit || "unit",
    category: input.category || "misc",
    brand: input.brand || "",
    image_url: input.image_url || "",
    expiryDate: input.expiryDate || null,
    in_stock: quantity > 0,
    source: input.source || "web-dashboard",
    addedAt: serverTimestamp(),
    updatedAt: serverTimestamp(),
  });

  await addDoc(collection(db, "usageLogs"), {
    item_id: docRef.id,
    item_name: input.name,
    event_type: "restocked",
    action_type: "restocked",
    delta: quantity || 1,
    quantity_changed: quantity || 1,
    quantity_after: quantity,
    timestamp: serverTimestamp(),
    source: input.source || "web-dashboard",
  });

  return docRef.id;
}

function normalizeName(name: string): string {
  return name.trim().replace(/\s+/g, " ").toLowerCase();
}

async function getUncheckedShoppingItems(): Promise<ShoppingItem[]> {
  const snap = await getDocs(query(collection(db, "shoppingList"), where("checked", "==", false)));
  return snap.docs.map((itemDoc) => ({
    ...(itemDoc.data() as ShoppingItem),
    id: itemDoc.id,
  }));
}

function findMatchingShoppingItem(
  items: ShoppingItem[],
  input: { name: string; barcode?: string }
): ShoppingItem | undefined {
  const barcode = input.barcode?.trim();
  if (barcode) {
    const barcodeMatch = items.find((item) => item.barcode === barcode);
    if (barcodeMatch) return barcodeMatch;
  }
  const normalized = normalizeName(input.name);
  return items.find((item) => normalizeName(item.name) === normalized);
}

export async function addShoppingItem(input: {
  name: string;
  quantity?: number;
  unit?: string;
  category?: string;
  barcode?: string;
  brand?: string;
  image_url?: string;
  addedBy?: ShoppingAddSource;
}) {
  const name = input.name.trim();
  if (!name) {
    throw new Error("Shopping item name is required.");
  }

  const quantity = Number.isFinite(input.quantity) && input.quantity && input.quantity > 0
    ? input.quantity
    : 1;
  const unchecked = await getUncheckedShoppingItems();
  const match = findMatchingShoppingItem(unchecked, {
    name,
    barcode: input.barcode,
  });

  if (match) {
    const newQuantity = Number(match.quantity || 0) + quantity;
    await updateDoc(doc(db, "shoppingList", match.id), {
      quantity: newQuantity,
      unit: match.unit || input.unit || "unit",
      category: match.category || input.category || "misc",
      barcode: match.barcode || input.barcode || "",
      brand: match.brand || input.brand || "",
      image_url: match.image_url || input.image_url || "",
      addedBy: match.addedBy || input.addedBy || "web-dashboard",
      updatedAt: serverTimestamp(),
    });
    return {
      action: "incremented" as const,
      id: match.id,
      name: match.name || name,
      quantity_added: quantity,
      quantity: newQuantity,
      unit: match.unit || input.unit || "unit",
    };
  }

  const docRef = await addDoc(collection(db, "shoppingList"), {
    name,
    quantity,
    unit: input.unit || "unit",
    category: input.category || "misc",
    barcode: input.barcode || "",
    brand: input.brand || "",
    image_url: input.image_url || "",
    addedBy: input.addedBy || "web-dashboard",
    checked: false,
    addedAt: serverTimestamp(),
    updatedAt: serverTimestamp(),
  });

  return {
    action: "created" as const,
    id: docRef.id,
    name,
    quantity_added: quantity,
    quantity,
    unit: input.unit || "unit",
  };
}

function quantityFromLookup(lookup: ProductLookup): number {
  if (typeof lookup.quantity === "number" && Number.isFinite(lookup.quantity) && lookup.quantity > 0) {
    return lookup.quantity;
  }
  return 1;
}

export async function lookupProductByUpc(upc: string): Promise<ProductLookup> {
  const sku = upc.trim();
  if (!/^\d{4,14}$/.test(sku)) {
    throw new Error("UPC must be 4 to 14 digits.");
  }

  const fields = "product_name,quantity,categories_tags,brands,nutriments,image_url";
  const url = `https://world.openfoodfacts.org/api/v2/product/${encodeURIComponent(sku)}.json?fields=${fields}`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Product lookup failed with ${response.status}.`);
  }
  const payload = await response.json();
  if (payload.status !== 1) {
    throw new Error(`UPC ${sku} was not found.`);
  }

  const product = payload.product || {};
  const rawQuantity = product.quantity || "";
  let quantity: number | null = null;
  let unit = "unit";
  const parts = String(rawQuantity).trim().split(/\s+/).filter(Boolean);
  if (parts.length > 0) {
    const parsed = Number.parseFloat(parts[0].replace(",", "."));
    if (Number.isFinite(parsed)) {
      quantity = parsed;
      unit = parts[1] || "unit";
    }
  }

  const categories = Array.isArray(product.categories_tags) ? product.categories_tags : [];
  const category = categories.length
    ? String(categories[categories.length - 1]).replace("en:", "").replaceAll("-", " ")
    : "misc";

  const lookup: ProductLookup = {
    sku,
    product_name: product.product_name || "Unknown Product",
    quantity,
    unit,
    category,
    brand: product.brands || "",
    image_url: product.image_url || "",
    raw_quantity: rawQuantity,
  };

  try {
    await setDoc(
      doc(db, "productLookups", sku),
      { ...lookup, updatedAt: serverTimestamp() },
      { merge: true }
    );
  } catch (error) {
    console.warn("Product lookup cache write failed; continuing with inventory add.", error);
  }

  return lookup;
}

export async function addBarcodeToPantry(upc: string) {
  const lookup = await lookupProductByUpc(upc);
  const quantityToAdd = quantityFromLookup(lookup);
  const matches = await getDocs(
    query(collection(db, "pantryItems"), where("barcode", "==", lookup.sku), limit(1))
  );

  if (!matches.empty) {
    const itemDoc = matches.docs[0];
    const current = itemDoc.data() as PantryItem;
    const currentQty = Number(current.quantity ?? current.amount ?? 0);
    const newQty = currentQty + quantityToAdd;
    const batch = writeBatch(db);
    batch.set(
      doc(db, "pantryItems", itemDoc.id),
      {
        name: current.name || lookup.product_name,
        barcode: lookup.sku,
        quantity: newQty,
        amount: newQty,
        unit: current.unit || lookup.unit,
        category: current.category || lookup.category,
        brand: current.brand || lookup.brand || "",
        image_url: current.image_url || lookup.image_url || "",
        in_stock: true,
        updatedAt: serverTimestamp(),
        source: current.source || "web-barcode-scan",
      },
      { merge: true }
    );
    batch.set(doc(collection(db, "usageLogs")), {
      item_id: itemDoc.id,
      item_name: current.name || lookup.product_name,
      sku: lookup.sku,
      event_type: "restocked",
      action_type: "restocked",
      delta: quantityToAdd,
      quantity_changed: quantityToAdd,
      quantity_after: newQty,
      timestamp: serverTimestamp(),
      source: "web-barcode-scan",
    });
    await batch.commit();
    return {
      action: "restocked" as const,
      id: itemDoc.id,
      name: current.name || lookup.product_name,
      quantity_added: quantityToAdd,
      unit: current.unit || lookup.unit,
    };
  }

  const id = await addPantryItem({
    name: lookup.product_name,
    barcode: lookup.sku,
    quantity: quantityToAdd,
    unit: lookup.unit,
    category: lookup.category,
    brand: lookup.brand,
    image_url: lookup.image_url,
    expiryDate: null,
    source: "web-barcode-scan",
  });

  return {
    action: "created" as const,
    id,
    name: lookup.product_name,
    quantity_added: quantityToAdd,
    unit: lookup.unit,
  };
}

export async function addBarcodeToShoppingList(upc: string) {
  const lookup = await lookupProductByUpc(upc);
  return addShoppingItem({
    name: lookup.product_name,
    barcode: lookup.sku,
    quantity: 1,
    unit: lookup.unit || "unit",
    category: lookup.category || "misc",
    brand: lookup.brand,
    image_url: lookup.image_url,
    addedBy: "barcode-scan",
  });
}

async function restockPantryFromShoppingItem(item: ShoppingItem) {
  const quantity = Number.isFinite(item.quantity) && item.quantity > 0 ? item.quantity : 1;
  const barcode = item.barcode?.trim();
  const matches = barcode
    ? await getDocs(query(collection(db, "pantryItems"), where("barcode", "==", barcode), limit(1)))
    : null;

  if (matches && !matches.empty) {
    const pantryDoc = matches.docs[0];
    const current = pantryDoc.data() as PantryItem;
    const currentQty = Number(current.quantity ?? current.amount ?? 0);
    const newQty = currentQty + quantity;
    const batch = writeBatch(db);
    batch.set(
      doc(db, "pantryItems", pantryDoc.id),
      {
        name: current.name || item.name,
        barcode: barcode || current.barcode || "",
        quantity: newQty,
        amount: newQty,
        unit: current.unit || item.unit || "unit",
        category: current.category || item.category || "misc",
        brand: current.brand || item.brand || "",
        image_url: current.image_url || item.image_url || "",
        in_stock: true,
        updatedAt: serverTimestamp(),
        source: current.source || "shopping-checkoff",
      },
      { merge: true }
    );
    batch.set(doc(collection(db, "usageLogs")), {
      item_id: pantryDoc.id,
      item_name: current.name || item.name,
      sku: barcode || null,
      event_type: "restocked",
      action_type: "restocked",
      delta: quantity,
      quantity_changed: quantity,
      quantity_after: newQty,
      timestamp: serverTimestamp(),
      source: "shopping-checkoff",
    });
    await batch.commit();
    return pantryDoc.id;
  }

  return addPantryItem({
    name: item.name,
    barcode: barcode || "",
    quantity,
    unit: item.unit || "unit",
    category: item.category || "misc",
    brand: item.brand,
    image_url: item.image_url,
    expiryDate: null,
    source: "shopping-checkoff",
  });
}

export async function toggleShoppingItemChecked(item: ShoppingItem) {
  const isNowChecked = !item.checked;
  await updateDoc(doc(db, "shoppingList", item.id), {
    checked: isNowChecked,
    updatedAt: serverTimestamp(),
  });

  if (isNowChecked) {
    await restockPantryFromShoppingItem(item);
  }

  return isNowChecked;
}

export async function performPantryAction(
  itemId: string,
  actionType: "cooked" | "discarded"
) {
  const itemRef = doc(db, "pantryItems", itemId);
  const snap = await getDoc(itemRef);
  if (!snap.exists()) {
    throw new Error("Item not found");
  }
  const item = snap.data() as PantryItem;
  const currentQty = Number(item.quantity ?? item.amount ?? 0);
  const batch = writeBatch(db);
  batch.set(doc(collection(db, "usageLogs")), {
    item_id: itemId,
    item_name: item.name,
    sku: item.barcode || null,
    event_type: actionType === "cooked" ? "consumed" : "expired",
    action_type: actionType,
    delta: currentQty || 1,
    quantity_changed: 1,
    quantity_after: 0,
    timestamp: serverTimestamp(),
    source: "web-dashboard",
  });
  batch.delete(itemRef);
  await batch.commit();
}

function parseIngredientAmount(ingredient: string): number {
  const match = ingredient.match(/^([\d.]+)/);
  const value = match ? Number.parseFloat(match[1]) : 1;
  if (!Number.isFinite(value)) return 1;
  const lower = ingredient.toLowerCase();
  if (lower.includes("cup")) return value * 8;
  if (lower.includes("tbsp") || lower.includes("tablespoon")) return value * 0.5;
  if (lower.includes("tsp") || lower.includes("teaspoon")) return value * 0.16;
  if (lower.includes("lb") || lower.includes("pound")) return value * 453.59;
  if (lower.includes("ml") || lower.includes("milliliter")) return value * 0.0338;
  return value;
}

export async function cookRecipeFromFirestore(recipeId: string) {
  const recipeSnap = await getDoc(doc(db, "recipes", recipeId));
  if (!recipeSnap.exists()) {
    throw new Error("Recipe not found");
  }
  const recipe = recipeSnap.data() as RecipeItem;
  const pantrySnap = await getDocs(collection(db, "pantryItems"));
  const pantryItems = pantrySnap.docs.map((itemDoc) => ({
    ...(itemDoc.data() as PantryItem),
    id: itemDoc.id,
  }));

  const batch = writeBatch(db);
  const deducted: { item_id: string; deducted: number; new_amount: number }[] = [];

  for (const ingredient of recipe.ingredients || []) {
    const lowerIngredient = ingredient.toLowerCase();
    const match = pantryItems.find((item) => {
      const lowerName = item.name?.toLowerCase() || "";
      return lowerName && (lowerIngredient.includes(lowerName) || lowerName.includes(lowerIngredient));
    });
    if (!match) continue;

    const amountToDeduct = parseIngredientAmount(ingredient);
    const currentQty = Number(match.quantity ?? match.amount ?? 0);
    const newQty = Math.max(0, currentQty - amountToDeduct);
    match.quantity = newQty;
    match.amount = newQty;
    deducted.push({ item_id: match.id, deducted: amountToDeduct, new_amount: newQty });

    batch.set(
      doc(db, "pantryItems", match.id),
      {
        quantity: newQty,
        amount: newQty,
        in_stock: newQty > 0,
        updatedAt: serverTimestamp(),
      },
      { merge: true }
    );
    batch.set(doc(collection(db, "usageLogs")), {
      item_id: match.id,
      item_name: match.name,
      recipe_id: recipeId,
      recipe_title: recipe.title,
      event_type: "consumed",
      action_type: "cooked",
      delta: amountToDeduct,
      quantity_changed: 1,
      quantity_after: newQty,
      timestamp: serverTimestamp(),
      source: "web-dashboard",
    });
  }

  await batch.commit();
  return deducted;
}

export async function requestRecipeDiscovery() {
  return addDoc(collection(db, "recipeRequests"), {
    type: "discover",
    status: "pending",
    createdBy: "web-dashboard",
    createdAt: serverTimestamp(),
  });
}

export async function requestSmartShoppingPlan() {
  return addDoc(collection(db, "smartPlanRequests"), {
    status: "pending",
    createdBy: "web-dashboard",
    createdAt: serverTimestamp(),
  });
}
