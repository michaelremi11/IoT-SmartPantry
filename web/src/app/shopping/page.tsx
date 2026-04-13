// web/src/app/shopping/page.tsx
// Remote shopping list viewer — real-time Firestore subscription.
"use client";

import { useEffect, useState } from "react";
import {
  subscribeShoppingList,
  ShoppingItem,
} from "@/lib/firestore";
import {
  doc,
  updateDoc,
  addDoc,
  collection,
  serverTimestamp,
} from "firebase/firestore";
import { db } from "@/lib/firebase";

export default function ShoppingPage() {
  const [items, setItems] = useState<ShoppingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [newItem, setNewItem] = useState("");

  useEffect(() => {
    const unsub = subscribeShoppingList((data) => {
      setItems(data);
      setLoading(false);
    });
    return () => unsub();
  }, []);

  const toggleChecked = async (item: ShoppingItem) => {
    await updateDoc(doc(db, "shoppingList", item.id), {
      checked: !item.checked,
    });
  };

  const addItem = async () => {
    const name = newItem.trim();
    if (!name) return;
    await addDoc(collection(db, "shoppingList"), {
      name,
      quantity: 1,
      addedBy: "web-dashboard",
      checked: false,
      addedAt: serverTimestamp(),
    });
    setNewItem("");
  };

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100 p-8">
      <div className="max-w-2xl mx-auto">
        <h1 className="text-3xl font-bold text-sky-400 mb-2">🛒 Shopping List</h1>
        <p className="text-gray-400 mb-6">
          Add items here — they'll appear on the kitchen hub instantly
        </p>

        {/* Add item */}
        <div className="flex gap-3 mb-8">
          <input
            type="text"
            placeholder="Add an item…"
            value={newItem}
            onChange={(e) => setNewItem(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addItem()}
            className="flex-1 px-4 py-2 rounded-lg bg-gray-800 border border-gray-700
                       text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2
                       focus:ring-sky-500"
          />
          <button
            onClick={addItem}
            className="px-5 py-2 rounded-lg bg-sky-500 hover:bg-sky-400
                       text-white font-semibold transition-colors"
          >
            Add
          </button>
        </div>

        {loading ? (
          <p className="text-gray-500 animate-pulse">Loading list…</p>
        ) : items.length === 0 ? (
          <p className="text-gray-500">Your shopping list is empty 🎉</p>
        ) : (
          <ul className="space-y-2">
            {items.map((item) => (
              <li
                key={item.id}
                onClick={() => toggleChecked(item)}
                className={`flex items-center gap-4 px-4 py-3 rounded-xl border cursor-pointer
                            transition-all duration-150
                            ${item.checked
                              ? "border-gray-700 bg-gray-900 opacity-50"
                              : "border-sky-800 bg-gray-900 hover:bg-gray-800"
                            }`}
              >
                <span
                  className={`w-5 h-5 rounded-full border-2 flex-shrink-0
                              ${item.checked ? "border-gray-600 bg-gray-600" : "border-sky-400"}`}
                >
                  {item.checked && (
                    <span className="block w-full h-full rounded-full bg-sky-400" />
                  )}
                </span>
                <span className={item.checked ? "line-through text-gray-500" : ""}>
                  {item.name}
                </span>
                {item.addedBy === "analytics-auto" && (
                  <span className="ml-auto text-xs text-amber-400">📊 auto</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
