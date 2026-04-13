// web/src/app/inventory/page.tsx
// Remote pantry inventory viewer — real-time Firestore subscription.
"use client";

import { useEffect, useState } from "react";
import { subscribePantry, PantryItem } from "@/lib/firestore";

export default function InventoryPage() {
  const [items, setItems] = useState<PantryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    const unsub = subscribePantry((data) => {
      setItems(data);
      setLoading(false);
    });
    return () => unsub();
  }, []);

  const filtered = items.filter((i) =>
    i.name.toLowerCase().includes(search.toLowerCase())
  );

  const expiringSoon = (expiry?: string) => {
    if (!expiry) return false;
    const diff = (new Date(expiry).getTime() - Date.now()) / 86400000;
    return diff >= 0 && diff <= 3;
  };

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100 p-8">
      <div className="max-w-5xl mx-auto">
        <h1 className="text-3xl font-bold text-emerald-400 mb-2">
          🥦 Pantry Inventory
        </h1>
        <p className="text-gray-400 mb-6">Live view synced from the kitchen hub</p>

        <input
          type="search"
          placeholder="Search items..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full mb-6 px-4 py-2 rounded-lg bg-gray-800 border border-gray-700
                     text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2
                     focus:ring-emerald-500"
        />

        {loading ? (
          <p className="text-gray-500 animate-pulse">Loading inventory…</p>
        ) : filtered.length === 0 ? (
          <p className="text-gray-500">No items found.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-gray-800">
            <table className="w-full text-sm">
              <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
                <tr>
                  {["Name", "Qty", "Unit", "Expires", "Category"].map((h) => (
                    <th key={h} className="px-4 py-3 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((item) => (
                  <tr
                    key={item.id}
                    className="border-t border-gray-800 hover:bg-gray-900 transition-colors"
                  >
                    <td className="px-4 py-3 font-medium">{item.name}</td>
                    <td className="px-4 py-3">{item.quantity}</td>
                    <td className="px-4 py-3 text-gray-400">{item.unit}</td>
                    <td className="px-4 py-3">
                      <span
                        className={
                          expiringSoon(item.expiryDate)
                            ? "text-amber-400 font-semibold"
                            : "text-gray-400"
                        }
                      >
                        {item.expiryDate || "—"}
                        {expiringSoon(item.expiryDate) && " ⚠️"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-400">{item.category || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}
