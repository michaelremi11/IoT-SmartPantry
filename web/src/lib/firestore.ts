// web/src/lib/firestore.ts
// Helper functions for reading pantry and shopping list data from Firestore.

import {
  collection,
  onSnapshot,
  query,
  orderBy,
  Unsubscribe,
  DocumentData,
  QuerySnapshot,
} from "firebase/firestore";
import { db } from "./firebase";

export interface PantryItem {
  id: string;
  name: string;
  barcode?: string;
  quantity: number;
  unit: string;
  expiryDate?: string;
  category?: string;
  addedAt?: Date;
  updatedAt?: Date;
}

export interface ShoppingItem {
  id: string;
  name: string;
  quantity: number;
  addedBy?: string;
  checked: boolean;
  addedAt?: Date;
}

function mapDoc<T>(snap: QuerySnapshot<DocumentData>): T[] {
  return snap.docs.map((doc) => ({ id: doc.id, ...doc.data() } as T));
}

/** Subscribe to real-time pantry inventory updates. */
export function subscribePantry(
  callback: (items: PantryItem[]) => void
): Unsubscribe {
  const q = query(collection(db, "pantryItems"), orderBy("name"));
  return onSnapshot(q, (snap) => callback(mapDoc<PantryItem>(snap)));
}

/** Subscribe to real-time shopping list updates. */
export function subscribeShoppingList(
  callback: (items: ShoppingItem[]) => void
): Unsubscribe {
  const q = query(collection(db, "shoppingList"), orderBy("addedAt", "desc"));
  return onSnapshot(q, (snap) => callback(mapDoc<ShoppingItem>(snap)));
}
