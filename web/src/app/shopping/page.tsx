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
  const [smartPlan, setSmartPlan] = useState<any>(null);
  const [generating, setGenerating] = useState(false);

  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  useEffect(() => {
    const unsub = subscribeShoppingList((data) => {
      setItems(data);
      setLoading(false);
    });
    return () => unsub();
  }, []);

  const toggleChecked = async (item: ShoppingItem) => {
    const isNowChecked = !item.checked;
    await updateDoc(doc(db, "shoppingList", item.id), {
      checked: isNowChecked,
    });
    
    // Auto-restock if we checked it off
    if (isNowChecked) {
      try {
        await fetch(`${API_URL}/inventory`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
             name: item.name,
             category: "misc",
             amount: 1,
             quantity: 1,
             unit: "unit",
             in_stock: true,
             expiryDate: null
          })
        });
      } catch(e) {
        console.error("Failed to restock item", e);
      }
    }
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

  const generateSmartPlan = async () => {
    setGenerating(true);
    try {
      const res = await fetch(`${API_URL}/shopping/smart-plan`);
      const data = await res.json();
      setSmartPlan(data);
    } catch(e) {
      console.error(e);
    } finally {
      setGenerating(false);
    }
  };

  const addPlanItem = async (name: string) => {
    await addDoc(collection(db, "shoppingList"), {
      name,
      quantity: 1,
      addedBy: "analytics-auto",
      checked: false,
      addedAt: serverTimestamp(),
    });
  };

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100 p-8">
      <div className="max-w-2xl mx-auto">
        <h1 className="text-3xl font-bold text-sky-400 mb-2">🛒 Shopping List</h1>
        <p className="text-gray-400 mb-6">
          Add items here — they'll appear on the kitchen hub instantly
        </p>

        <div className="flex flex-col sm:flex-row gap-4 mb-6">
          <button 
            onClick={generateSmartPlan} 
            disabled={generating}
            className="w-full sm:w-auto bg-indigo-600 hover:bg-indigo-500 text-white font-medium px-4 py-2 rounded-lg transition shadow flex gap-2 items-center justify-center"
          >
            {generating ? "Computing..." : "🤖 Generate Smart Weekly Plan"}
          </button>
          
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

        {smartPlan && (
          <div className="mb-8 p-5 bg-indigo-950/20 border border-indigo-900/50 rounded-xl space-y-4 animate-in fade-in slide-in-from-top-4">
            <div className="flex justify-between items-center">
              <h2 className="text-lg font-bold text-indigo-400">Suggested Smart Plan</h2>
              <button onClick={() => setSmartPlan(null)} className="text-indigo-500 hover:text-indigo-300 text-sm">Dismiss</button>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
               <div>
                  <h3 className="font-bold text-xs uppercase text-gray-500 mb-2">Restock Staples</h3>
                  <ul className="space-y-2">
                    {smartPlan.staples?.map((i: any, idx: number) => (
                      <li key={idx} className="flex justify-between items-center text-sm bg-gray-900 p-2 rounded">
                        <span className="text-gray-300 truncate pr-2">{i.item}</span>
                        <button onClick={()=>addPlanItem(i.item)} className="bg-sky-900/50 hover:bg-sky-800 text-sky-400 px-2 py-1 rounded text-xs">+</button>
                      </li>
                    ))}
                  </ul>
               </div>
               <div>
                  <h3 className="font-bold text-xs uppercase text-gray-500 mb-2">High Impact Unlocks</h3>
                  <ul className="space-y-2">
                    {smartPlan.unlocks?.map((i: any, idx: number) => (
                      <li key={idx} className="flex justify-between items-center text-sm bg-gray-900 p-2 rounded">
                        <span className="text-emerald-400 truncate pr-2">{i.item}</span>
                        <button onClick={()=>addPlanItem(i.item)} className="bg-sky-900/50 hover:bg-sky-800 text-sky-400 px-2 py-1 rounded text-xs">+</button>
                      </li>
                    ))}
                  </ul>
               </div>
               <div>
                  <h3 className="font-bold text-xs uppercase text-gray-500 mb-2">Waste Prevention</h3>
                  <ul className="space-y-2">
                    {smartPlan.waste_prevention?.map((i: any, idx: number) => (
                      <li key={idx} className="flex justify-between items-center text-sm bg-gray-900 p-2 rounded">
                        <span className="text-amber-400 truncate pr-2" title={i.reason}>{i.item}</span>
                        <button className="bg-amber-900/30 text-amber-500 px-2 py-1 rounded text-[10px]" disabled>Cook It!</button>
                      </li>
                    ))}
                  </ul>
               </div>
            </div>
          </div>
        )}

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
