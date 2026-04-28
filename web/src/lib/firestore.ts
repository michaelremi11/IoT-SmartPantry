// web/src/lib/firestore.ts
// Helper functions for reading pantry and shopping list data from Firestore.

import {
  collection,
  addDoc,
  deleteDoc,
  doc,
  getDoc,
  getDocs,
  onSnapshot,
  query,
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

export interface WorkerRequestStatus {
  id: string;
  status: "pending" | "processing" | "complete" | "error";
  error?: string | null;
  createdAt?: unknown;
  startedAt?: unknown;
  completedAt?: unknown;
  recipeIds?: string[];
  planId?: string;
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
type HouseholdScopedInput = { householdId: string };

type PantryMatchable = Pick<PantryItem, "id" | "name" | "quantity" | "amount" | "unit">;

type IngredientIdentity = {
  normalized: string;
  tokens: string[];
  family?: string;
  group?: string;
};

type UnitDimension = "count" | "volume" | "weight" | "unknown";

export interface RecipeIngredient {
  item?: string;
  name: string;
  amount?: number;
  unit?: string;
  canonical?: string;
  family?: string;
  group?: string;
  optional?: boolean;
  display?: string;
}

export type StoredRecipeIngredient = string | RecipeIngredient;

const LEADING_MEASUREMENT_PATTERN =
  /^\s*(?:\d+(?:\.\d+)?(?:\/\d+(?:\.\d+)?)?|\d+\/\d+)\s*/;
const COMMON_INGREDIENT_FILLER = new Set([
  "a",
  "an",
  "and",
  "approx",
  "approximately",
  "bag",
  "box",
  "brand",
  "can",
  "cups",
  "cup",
  "fresh",
  "frozen",
  "grams",
  "gram",
  "large",
  "lb",
  "medium",
  "ml",
  "of",
  "ounce",
  "ounces",
  "oz",
  "package",
  "packages",
  "piece",
  "pieces",
  "pkg",
  "pound",
  "pounds",
  "small",
  "extra",
  "virgin",
  "whole",
  "skim",
  "reduced",
  "fat",
  "lowfat",
  "original",
  "tablespoon",
  "tablespoons",
  "tbsp",
  "teaspoon",
  "teaspoons",
  "tsp",
  "unit",
  "units",
]);

const FAMILY_GROUP_KEYWORDS: Array<{
  family: string;
  group?: string;
  keywords: string[];
}> = [
  {
    family: "pasta",
    group: "long_pasta",
    keywords: [
      "spaghetti",
      "linguine",
      "fettuccine",
      "angel hair",
      "capellini",
      "bucatini",
      "vermicelli",
      "pappardelle",
      "tagliatelle",
    ],
  },
  {
    family: "pasta",
    group: "shaped_pasta",
    keywords: [
      "penne",
      "rigatoni",
      "rotini",
      "fusilli",
      "macaroni",
      "elbow macaroni",
      "cavatappi",
      "farfalle",
      "ziti",
      "gemelli",
      "shells",
    ],
  },
  {
    family: "pasta",
    group: "small_pasta",
    keywords: ["orzo", "ditalini", "stelline", "acini di pepe"],
  },
  {
    family: "pasta",
    group: "sheet_pasta",
    keywords: ["lasagna", "lasagne"],
  },
  {
    family: "pasta",
    group: "stuffed_pasta",
    keywords: ["ravioli", "tortellini"],
  },
  {
    family: "milk",
    group: "oat_milk",
    keywords: ["oat milk"],
  },
  {
    family: "milk",
    group: "almond_milk",
    keywords: ["almond milk"],
  },
  {
    family: "milk",
    group: "soy_milk",
    keywords: ["soy milk"],
  },
  {
    family: "milk",
    group: "coconut_milk",
    keywords: ["coconut milk"],
  },
  {
    family: "milk",
    group: "cashew_milk",
    keywords: ["cashew milk"],
  },
  {
    family: "oil",
    group: "olive_oil",
    keywords: ["olive oil", "extra virgin olive oil"],
  },
  {
    family: "oil",
    group: "vegetable_oil",
    keywords: ["vegetable oil", "canola oil"],
  },
];

const UNIT_DEFINITIONS: Record<string, { dimension: UnitDimension; factor: number }> = {
  unit: { dimension: "count", factor: 1 },
  units: { dimension: "count", factor: 1 },
  count: { dimension: "count", factor: 1 },
  piece: { dimension: "count", factor: 1 },
  pieces: { dimension: "count", factor: 1 },
  item: { dimension: "count", factor: 1 },
  items: { dimension: "count", factor: 1 },
  egg: { dimension: "count", factor: 1 },
  eggs: { dimension: "count", factor: 1 },
  clove: { dimension: "count", factor: 1 },
  cloves: { dimension: "count", factor: 1 },
  slice: { dimension: "count", factor: 1 },
  slices: { dimension: "count", factor: 1 },
  cup: { dimension: "volume", factor: 8 },
  cups: { dimension: "volume", factor: 8 },
  tbsp: { dimension: "volume", factor: 0.5 },
  tablespoon: { dimension: "volume", factor: 0.5 },
  tablespoons: { dimension: "volume", factor: 0.5 },
  tsp: { dimension: "volume", factor: 1 / 6 },
  teaspoon: { dimension: "volume", factor: 1 / 6 },
  teaspoons: { dimension: "volume", factor: 1 / 6 },
  "fl oz": { dimension: "volume", factor: 1 },
  floz: { dimension: "volume", factor: 1 },
  ml: { dimension: "volume", factor: 0.033814 },
  l: { dimension: "volume", factor: 33.814 },
  oz: { dimension: "weight", factor: 28.3495 },
  ounce: { dimension: "weight", factor: 28.3495 },
  ounces: { dimension: "weight", factor: 28.3495 },
  lb: { dimension: "weight", factor: 453.592 },
  lbs: { dimension: "weight", factor: 453.592 },
  pound: { dimension: "weight", factor: 453.592 },
  pounds: { dimension: "weight", factor: 453.592 },
  g: { dimension: "weight", factor: 1 },
  gram: { dimension: "weight", factor: 1 },
  grams: { dimension: "weight", factor: 1 },
  kg: { dimension: "weight", factor: 1000 },
};

function mapDoc<T>(snap: QuerySnapshot): T[] {
  return snap.docs.map((doc) => ({ id: doc.id, ...doc.data() } as T));
}

function requireHouseholdId(householdId: string) {
  const value = householdId.trim();
  if (!value) {
    throw new Error("A household is required for this action.");
  }
  return value;
}

/** Subscribe to real-time pantry inventory updates. */
export function subscribePantry(
  householdId: string,
  callback: (items: PantryItem[]) => void
): Unsubscribe {
  const q = query(
    collection(db, "pantryItems"),
    where("householdId", "==", requireHouseholdId(householdId))
  );
  return onSnapshot(q, (snap) =>
    callback(mapDoc<PantryItem>(snap).sort((left, right) => left.name.localeCompare(right.name)))
  );
}

export function subscribeShoppingList(
  householdId: string,
  callback: (items: ShoppingItem[]) => void
): Unsubscribe {
  const q = query(
    collection(db, "shoppingList"),
    where("householdId", "==", requireHouseholdId(householdId))
  );
  return onSnapshot(q, (snap) =>
    callback(
      mapDoc<ShoppingItem>(snap).sort((left, right) => {
        const leftSeconds = (left.addedAt as unknown as FirestoreTimestamp | undefined)?.seconds ?? 0;
        const rightSeconds = (right.addedAt as unknown as FirestoreTimestamp | undefined)?.seconds ?? 0;
        return rightSeconds - leftSeconds;
      })
    )
  );
}

export interface RecipeItem {
  id?: string;
  title: string;
  ingredients: StoredRecipeIngredient[];
  instructions: string;
  source: string;
  estimated_time?: string;
  created_at?: FirestoreTimestamp;
}

/** Subscribe to real-time recipe updates. */
export function subscribeRecipes(
  householdId: string,
  callback: (items: RecipeItem[]) => void
): Unsubscribe {
  const q = query(collection(db, "recipes"), where("householdId", "==", requireHouseholdId(householdId)));
  return onSnapshot(q, (snap) => callback(mapDoc<RecipeItem>(snap)));
}

/** Subscribe to a server-generated analytics summary document. */
export function subscribeAnalyticsSummary<T>(
  householdId: string,
  docId: string,
  callback: (data: T | null) => void
): Unsubscribe {
  return onSnapshot(doc(db, "analyticsSummaries", `${requireHouseholdId(householdId)}_${docId}`), (snap) => {
    callback(snap.exists() ? ({ id: snap.id, ...snap.data() } as unknown as T) : null);
  });
}

export function subscribeSmartShoppingPlan(
  householdId: string,
  callback: (plan: SmartShoppingPlan | null) => void
): Unsubscribe {
  return onSnapshot(doc(db, "smartShoppingPlans", `${requireHouseholdId(householdId)}_current`), (snap) => {
    callback(snap.exists() ? (snap.data() as SmartShoppingPlan) : null);
  });
}

export function subscribeWorkerRequestStatus(
  collectionName: string,
  requestId: string,
  callback: (request: WorkerRequestStatus | null) => void
): Unsubscribe {
  return onSnapshot(doc(db, collectionName, requestId), (snap) => {
    callback(
      snap.exists()
        ? ({ id: snap.id, ...snap.data() } as WorkerRequestStatus)
        : null
    );
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
} & HouseholdScopedInput) {
  const quantity = Number.isFinite(input.quantity) ? input.quantity : 0;
  const householdId = requireHouseholdId(input.householdId);
  const docRef = await addDoc(collection(db, "pantryItems"), {
    householdId,
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
    householdId,
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

export function normalizeName(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9%/]+/g, " ")
    .replace(/\s+/g, " ");
}

function parseFractionalNumber(raw: string): number | null {
  const value = raw.trim();
  if (!value) {
    return null;
  }
  if (value.includes("/")) {
    const [numerator, denominator] = value.split("/");
    const left = Number.parseFloat(numerator);
    const right = Number.parseFloat(denominator);
    if (Number.isFinite(left) && Number.isFinite(right) && right !== 0) {
      return left / right;
    }
  }
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeUnit(unit?: string): string {
  return normalizeName(unit || "").replace(/\s+/g, " ").trim();
}

function getUnitDefinition(unit?: string) {
  const normalized = normalizeUnit(unit);
  if (!normalized) {
    return { normalized: "unit", dimension: "count" as UnitDimension, factor: 1 };
  }
  return {
    normalized,
    ...(UNIT_DEFINITIONS[normalized] || { dimension: "unknown" as UnitDimension, factor: 1 }),
  };
}

function toComparableAmount(amount: number, unit?: string): number {
  const definition = getUnitDefinition(unit);
  return amount * definition.factor;
}

function fromComparableAmount(amount: number, unit?: string): number {
  const definition = getUnitDefinition(unit);
  return amount / definition.factor;
}

function roundComparableAmount(amount: number): number {
  return Math.round(amount * 1000) / 1000;
}

function parseLegacyIngredient(raw: string): RecipeIngredient {
  const trimmed = raw.trim();
  const match = trimmed.match(
    /^(\d+(?:\.\d+)?(?:\/\d+(?:\.\d+)?)?|\d+\/\d+)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)\s+(.+)$/
  );
  if (match) {
    const amount = parseFractionalNumber(match[1]);
    const unit = match[2];
    const name = match[3].trim();
    return {
      name,
      amount: amount ?? 1,
      unit,
      canonical: normalizeName(name),
      display: trimmed,
    };
  }

  const amountOnlyMatch = trimmed.match(/^(\d+(?:\.\d+)?(?:\/\d+(?:\.\d+)?)?|\d+\/\d+)\s+(.+)$/);
  if (amountOnlyMatch) {
    const amount = parseFractionalNumber(amountOnlyMatch[1]);
    const name = amountOnlyMatch[2].trim();
    return {
      name,
      amount: amount ?? 1,
      canonical: normalizeName(name),
      display: trimmed,
    };
  }

  return {
    name: trimmed,
    amount: 1,
    canonical: normalizeName(trimmed),
    display: trimmed,
  };
}

export function coerceRecipeIngredient(ingredient: StoredRecipeIngredient): RecipeIngredient {
  if (typeof ingredient === "string") {
    return parseLegacyIngredient(ingredient);
  }
  const name = ingredient.name?.trim() || ingredient.item?.trim() || ingredient.display?.trim() || "Unknown ingredient";
  return {
    ...ingredient,
    name,
    canonical: ingredient.canonical || normalizeName(name),
    display: ingredient.display || recipeIngredientToText({ ...ingredient, name }),
  };
}

export function getRecipeIngredientList(ingredients: StoredRecipeIngredient[]): RecipeIngredient[] {
  return ingredients.map((ingredient) => coerceRecipeIngredient(ingredient));
}

export function recipeIngredientToText(ingredient: StoredRecipeIngredient | RecipeIngredient): string {
  const resolved = typeof ingredient === "string" ? parseLegacyIngredient(ingredient) : ingredient;
  if (resolved.display?.trim()) {
    return resolved.display.trim();
  }
  const name = resolved.name?.trim() || resolved.item?.trim() || "Unknown ingredient";
  if (resolved.amount && resolved.unit && normalizeUnit(resolved.unit) !== "unit") {
    return `${resolved.amount} ${resolved.unit} ${name}`;
  }
  if (resolved.amount) {
    return `${resolved.amount} ${name}`;
  }
  return name;
}

export function getRecipeIngredientComparableAmount(ingredient: StoredRecipeIngredient | RecipeIngredient): number {
  const resolved = typeof ingredient === "string" ? parseLegacyIngredient(ingredient) : ingredient;
  const amount = Number.isFinite(resolved.amount) ? Number(resolved.amount) : 1;
  return toComparableAmount(amount, resolved.unit);
}

function stripLeadingAmount(text: string): string {
  let cleaned = text.trim();
  while (LEADING_MEASUREMENT_PATTERN.test(cleaned)) {
    cleaned = cleaned.replace(LEADING_MEASUREMENT_PATTERN, "");
  }
  return cleaned.trim();
}

function tokenizeIngredientText(text: string): string[] {
  return normalizeName(stripLeadingAmount(text))
    .split(" ")
    .filter((token) => token && !COMMON_INGREDIENT_FILLER.has(token));
}

function classifyIngredientText(text: string): IngredientIdentity {
  const normalized = normalizeName(stripLeadingAmount(text));
  const tokens = tokenizeIngredientText(text);

  for (const entry of FAMILY_GROUP_KEYWORDS) {
    if (entry.keywords.some((keyword) => normalized.includes(normalizeName(keyword)))) {
      return {
        normalized,
        tokens,
        family: entry.family,
        group: entry.group,
      };
    }
  }

  if (normalized.includes("milk")) {
    return {
      normalized,
      tokens,
      family: "milk",
      group: "dairy_milk",
    };
  }

  if (normalized.includes("pasta") || normalized.includes("noodle")) {
    return {
      normalized,
      tokens,
      family: "pasta",
    };
  }

  return {
    normalized,
    tokens,
  };
}

function classifyStoredIngredient(ingredient: StoredRecipeIngredient | RecipeIngredient): IngredientIdentity {
  const resolved = typeof ingredient === "string" ? parseLegacyIngredient(ingredient) : ingredient;
  const reference = resolved.canonical || resolved.name || resolved.item || resolved.display || "";
  const identity = classifyIngredientText(reference);
  return {
    ...identity,
    family: resolved.family || identity.family,
    group: resolved.group || identity.group,
  };
}

function countTokenOverlap(a: string[], b: string[]): number {
  if (a.length === 0 || b.length === 0) {
    return 0;
  }
  const right = new Set(b);
  return a.reduce((count, token) => count + (right.has(token) ? 1 : 0), 0);
}

function getIngredientMatchStrength(
  ingredient: IngredientIdentity,
  pantryItem: IngredientIdentity
): number {
  if (!ingredient.normalized || !pantryItem.normalized) {
    return 0;
  }

  if (
    ingredient.normalized === pantryItem.normalized ||
    ingredient.normalized.includes(pantryItem.normalized) ||
    pantryItem.normalized.includes(ingredient.normalized)
  ) {
    return 5;
  }

  if (ingredient.family && pantryItem.family && ingredient.family === pantryItem.family) {
    if (ingredient.group && pantryItem.group) {
      return ingredient.group === pantryItem.group ? 4 : 0;
    }
    if (ingredient.group && !pantryItem.group) {
      return 1;
    }
    return 3;
  }

  const overlap = countTokenOverlap(ingredient.tokens, pantryItem.tokens);
  if (overlap >= 2) {
    return 2;
  }
  if (overlap === 1) {
    return 1;
  }

  return 0;
}

export function getItemQuantityValue(item: PantryMatchable): number {
  return Number(item.quantity ?? item.amount ?? 0);
}

export function getComparableItemQuantity(item: PantryMatchable): number {
  return toComparableAmount(getItemQuantityValue(item), item.unit);
}

function getMatchingPantryCandidates<T extends PantryMatchable>(
  ingredient: StoredRecipeIngredient | RecipeIngredient,
  items: T[]
) {
  const ingredientIdentity = classifyStoredIngredient(ingredient);
  return items
    .map((item) => ({
      item,
      quantity: getComparableItemQuantity(item),
      strength: getIngredientMatchStrength(
        ingredientIdentity,
        classifyIngredientText(item.name || "")
      ),
    }))
    .filter((candidate) => candidate.strength > 0 && candidate.quantity > 0)
    .sort((left, right) => {
      if (right.strength !== left.strength) {
        return right.strength - left.strength;
      }
      return left.quantity - right.quantity;
    });
}

export function getIngredientAvailableQuantity<T extends PantryMatchable>(
  ingredient: StoredRecipeIngredient | RecipeIngredient,
  items: T[]
): number {
  return getMatchingPantryCandidates(ingredient, items).reduce(
    (total, candidate) => total + candidate.quantity,
    0
  );
}

export function allocateIngredientAcrossPantry<T extends PantryMatchable>(
  ingredient: StoredRecipeIngredient | RecipeIngredient,
  amountNeeded: number,
  items: T[]
) {
  const candidates = getMatchingPantryCandidates(ingredient, items);
  const allocations: Array<{ item: T; used: number }> = [];
  let remaining = amountNeeded;

  for (const candidate of candidates) {
    if (remaining <= 0) {
      break;
    }
    const used = Math.min(candidate.quantity, remaining);
    if (used <= 0) {
      continue;
    }
    allocations.push({ item: candidate.item, used });
    remaining -= used;
  }

  const totalAvailable = candidates.reduce((total, candidate) => total + candidate.quantity, 0);

  return {
    satisfied: remaining <= 0,
    totalAvailable,
    allocations,
    remaining,
  };
}

async function getUncheckedShoppingItems(householdId: string): Promise<ShoppingItem[]> {
  const snap = await getDocs(
    query(
      collection(db, "shoppingList"),
      where("householdId", "==", requireHouseholdId(householdId)),
      where("checked", "==", false)
    )
  );
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
} & HouseholdScopedInput) {
  const name = input.name.trim();
  if (!name) {
    throw new Error("Shopping item name is required.");
  }
  const householdId = requireHouseholdId(input.householdId);

  const quantity = Number.isFinite(input.quantity) && input.quantity && input.quantity > 0
    ? input.quantity
    : 1;
  const unchecked = await getUncheckedShoppingItems(householdId);
  const match = findMatchingShoppingItem(unchecked, {
    name,
    barcode: input.barcode,
  });

  if (match) {
    const newQuantity = Number(match.quantity || 0) + quantity;
    await updateDoc(doc(db, "shoppingList", match.id), {
      householdId,
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
    householdId,
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

export async function addBarcodeToPantry(upc: string, householdId: string) {
  const scopedHouseholdId = requireHouseholdId(householdId);
  const lookup = await lookupProductByUpc(upc);
  const quantityToAdd = quantityFromLookup(lookup);
  const matches = await getDocs(
    query(
      collection(db, "pantryItems"),
      where("householdId", "==", scopedHouseholdId),
      where("barcode", "==", lookup.sku),
      limit(1)
    )
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
        householdId: scopedHouseholdId,
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
      householdId: scopedHouseholdId,
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
    householdId: scopedHouseholdId,
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

export async function addBarcodeToShoppingList(upc: string, householdId: string) {
  const lookup = await lookupProductByUpc(upc);
  return addShoppingItem({
    householdId,
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

async function restockPantryFromShoppingItem(householdId: string, item: ShoppingItem) {
  const quantity = Number.isFinite(item.quantity) && item.quantity > 0 ? item.quantity : 1;
  const barcode = item.barcode?.trim();
  const matches = barcode
    ? await getDocs(
        query(
          collection(db, "pantryItems"),
          where("householdId", "==", requireHouseholdId(householdId)),
          where("barcode", "==", barcode),
          limit(1)
        )
      )
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
        householdId,
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
      householdId,
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
    householdId,
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

  return isNowChecked;
}

export async function clearCheckedShoppingItems(householdId: string) {
  const checkedSnap = await getDocs(
    query(
      collection(db, "shoppingList"),
      where("householdId", "==", requireHouseholdId(householdId)),
      where("checked", "==", true)
    )
  );

  const checkedItems = checkedSnap.docs.map((itemDoc) => ({
    ...(itemDoc.data() as ShoppingItem),
    id: itemDoc.id,
  }));

  for (const item of checkedItems) {
    await restockPantryFromShoppingItem(householdId, item);
  }

  const batch = writeBatch(db);
  checkedSnap.docs.forEach((itemDoc) => {
    batch.delete(itemDoc.ref);
  });
  await batch.commit();

  return checkedItems.length;
}

export async function clearAllShoppingItems(householdId: string) {
  const allSnap = await getDocs(
    query(collection(db, "shoppingList"), where("householdId", "==", requireHouseholdId(householdId)))
  );
  const checkedItems: ShoppingItem[] = [];

  allSnap.docs.forEach((itemDoc) => {
    const item = { ...(itemDoc.data() as ShoppingItem), id: itemDoc.id };
    if (item.checked) {
      checkedItems.push(item);
    }
  });

  for (const item of checkedItems) {
    await restockPantryFromShoppingItem(householdId, item);
  }

  const batch = writeBatch(db);
  allSnap.docs.forEach((itemDoc) => {
    batch.delete(itemDoc.ref);
  });
  await batch.commit();

  return {
    removed: allSnap.size,
    restocked: checkedItems.length,
  };
}

export async function performPantryAction(
  itemId: string,
  actionType: "cooked" | "discarded",
  householdId: string
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
    householdId: requireHouseholdId(householdId),
    item_id: itemId,
    item_name: item.name,
    sku: item.barcode || null,
    event_type: actionType === "cooked" ? "consumed" : "expired",
    action_type: actionType,
    delta: currentQty || 1,
    quantity_changed: currentQty || 1,
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

export async function cookRecipeFromFirestore(recipeId: string, householdId: string) {
  const recipeSnap = await getDoc(doc(db, "recipes", recipeId));
  if (!recipeSnap.exists()) {
    throw new Error("Recipe not found");
  }
  const recipe = recipeSnap.data() as RecipeItem;
  const pantrySnap = await getDocs(
    query(collection(db, "pantryItems"), where("householdId", "==", requireHouseholdId(householdId)))
  );
  const pantryItems = pantrySnap.docs.map((itemDoc) => ({
    ...(itemDoc.data() as PantryItem),
    id: itemDoc.id,
  }));
  const recipeIngredients = getRecipeIngredientList(recipe.ingredients || []);

  const batch = writeBatch(db);
  const deducted: { item_id: string; deducted: number; new_amount: number }[] = [];
  const missing: string[] = [];

  for (const ingredient of recipeIngredients) {
    const amountToDeduct =
      typeof ingredient === "string" ? parseIngredientAmount(ingredient) : getRecipeIngredientComparableAmount(ingredient);
    const allocation = allocateIngredientAcrossPantry(ingredient, amountToDeduct, pantryItems);
    if (!allocation.satisfied) {
      missing.push(recipeIngredientToText(ingredient));
    }
  }

  if (missing.length > 0) {
    throw new Error(`Missing or insufficient pantry items: ${missing.join(", ")}`);
  }

  for (const ingredient of recipeIngredients) {
    const amountToDeduct =
      typeof ingredient === "string" ? parseIngredientAmount(ingredient) : getRecipeIngredientComparableAmount(ingredient);
    const allocation = allocateIngredientAcrossPantry(ingredient, amountToDeduct, pantryItems);
    for (const { item, used } of allocation.allocations) {
      const currentComparable = getComparableItemQuantity(item);
      const newComparable = Math.max(0, currentComparable - used);
      const newQty = roundComparableAmount(fromComparableAmount(newComparable, item.unit));
      item.quantity = newQty;
      item.amount = newQty;
      deducted.push({ item_id: item.id, deducted: used, new_amount: newQty });

      if (newQty <= 0) {
        batch.delete(doc(db, "pantryItems", item.id));
      } else {
        batch.set(
          doc(db, "pantryItems", item.id),
          {
            quantity: newQty,
            amount: newQty,
            in_stock: true,
            updatedAt: serverTimestamp(),
          },
          { merge: true }
        );
      }
      batch.set(doc(collection(db, "usageLogs")), {
        householdId: requireHouseholdId(householdId),
        item_id: item.id,
        item_name: item.name,
        recipe_id: recipeId,
        recipe_title: recipe.title,
        event_type: "consumed",
        action_type: "cooked",
        delta: used,
        quantity_changed: used,
        quantity_after: newQty,
        timestamp: serverTimestamp(),
        source: "web-dashboard",
      });
    }
  }

  await batch.commit();
  return deducted;
}

export async function requestRecipeDiscovery(householdId: string) {
  const requestRef = await addDoc(collection(db, "recipeRequests"), {
    householdId: requireHouseholdId(householdId),
    type: "discover",
    status: "pending",
    createdBy: "web-dashboard",
    createdAt: serverTimestamp(),
  });
  return requestRef.id;
}

export async function requestSmartShoppingPlan(householdId: string) {
  const requestRef = await addDoc(collection(db, "smartPlanRequests"), {
    householdId: requireHouseholdId(householdId),
    status: "pending",
    createdBy: "web-dashboard",
    createdAt: serverTimestamp(),
  });
  return requestRef.id;
}

export async function deleteRecipe(recipeId: string) {
  await deleteDoc(doc(db, "recipes", recipeId));
}

export async function clearAllRecipes(householdId: string) {
  const recipeSnap = await getDocs(
    query(collection(db, "recipes"), where("householdId", "==", requireHouseholdId(householdId)))
  );
  const batch = writeBatch(db);
  recipeSnap.docs.forEach((recipeDoc) => {
    batch.delete(recipeDoc.ref);
  });
  await batch.commit();
  return recipeSnap.size;
}
