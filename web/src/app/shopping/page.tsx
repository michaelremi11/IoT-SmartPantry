// web/src/app/shopping/page.tsx
// Remote shopping list viewer — real-time Firestore subscription.
"use client";

import { useEffect, useRef, useState } from "react";
import {
  addBarcodeToShoppingList,
  addShoppingItem,
  clearAllShoppingItems,
  clearCheckedShoppingItems,
  requestSmartShoppingPlan,
  SmartShoppingPlan,
  subscribeSmartShoppingPlan,
  subscribeShoppingList,
  subscribeWorkerRequestStatus,
  ShoppingItem,
  toggleShoppingItemChecked,
  WorkerRequestStatus,
} from "@/lib/firestore";

export default function ShoppingPage() {
  const [items, setItems] = useState<ShoppingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [newItem, setNewItem] = useState("");
  const [scanUpc, setScanUpc] = useState("");
  const [scanStatus, setScanStatus] = useState("");
  const [scanBusy, setScanBusy] = useState(false);
  const scanInputRef = useRef<HTMLInputElement | null>(null);
  const [smartPlan, setSmartPlan] = useState<SmartShoppingPlan | null>(null);
  const [generating, setGenerating] = useState(false);
  const [planRequestId, setPlanRequestId] = useState("");
  const [planStatus, setPlanStatus] = useState("");
  const [listStatus, setListStatus] = useState("");

  useEffect(() => {
    const unsub = subscribeShoppingList((data) => {
      setItems(data);
      setLoading(false);
    });
    const unsubPlan = subscribeSmartShoppingPlan(setSmartPlan);
    return () => {
      unsub();
      unsubPlan();
    };
  }, []);

  useEffect(() => {
    if (!planRequestId) return;

    const unsub = subscribeWorkerRequestStatus(
      "smartPlanRequests",
      planRequestId,
      (request: WorkerRequestStatus | null) => {
        if (!request) return;
        if (request.status === "pending") {
          setPlanStatus("Smart weekly plan queued. Waiting for the worker...");
          return;
        }
        if (request.status === "processing") {
          setPlanStatus("Smart weekly plan is being generated...");
          return;
        }
        if (request.status === "complete") {
          setGenerating(false);
          setPlanStatus("Smart weekly plan refreshed.");
          setPlanRequestId("");
          return;
        }
        if (request.status === "error") {
          setGenerating(false);
          setPlanStatus(request.error || "Smart weekly plan failed.");
          setPlanRequestId("");
        }
      }
    );

    return unsub;
  }, [planRequestId]);

  const toggleChecked = async (item: ShoppingItem) => {
    try {
      await toggleShoppingItemChecked(item);
    } catch (error) {
      console.error("Failed to update shopping item", error);
      window.alert("Could not update this shopping item. Please try again.");
    }
  };

  const addItem = async () => {
    const name = newItem.trim();
    if (!name) return;
    await addShoppingItem({
      name,
      unit: "unit",
      addedBy: "web-dashboard",
    });
    setNewItem("");
  };

  const handleBarcodeScan = async (e: React.FormEvent) => {
    e.preventDefault();
    const upc = scanUpc.trim();
    if (!upc || scanBusy) return;

    setScanBusy(true);
    setScanStatus(`Looking up UPC ${upc}...`);
    try {
      const result = await addBarcodeToShoppingList(upc);
      const verb = result.action === "incremented" ? "Updated" : "Added";
      setScanStatus(`${verb}: ${result.name} (+${result.quantity_added})`);
      setScanUpc("");
    } catch (error) {
      console.error("Shopping barcode scan failed", error);
      setScanStatus(error instanceof Error ? error.message : "Could not add that UPC.");
    } finally {
      setScanBusy(false);
      requestAnimationFrame(() => scanInputRef.current?.focus());
    }
  };

  const generateSmartPlan = async () => {
    setGenerating(true);
    setPlanStatus("");
    try {
      const requestId = await requestSmartShoppingPlan();
      setPlanRequestId(requestId);
      setPlanStatus("Smart weekly plan queued. Waiting for the worker...");
    } catch (e) {
      console.error(e);
      setPlanStatus("Could not queue the smart weekly plan.");
    } finally {
      setGenerating(false);
    }
  };

  const addPlanItem = async (name: string) => {
    await addShoppingItem({
      name,
      addedBy: "analytics-auto",
    });
  };

  const clearPurchased = async () => {
    const checkedCount = items.filter((item) => item.checked).length;
    if (checkedCount === 0) {
      setListStatus("No checked items to clear yet.");
      return;
    }
    if (!window.confirm(`Clear ${checkedCount} checked item(s) and add them to pantry inventory?`)) {
      return;
    }
    try {
      const removed = await clearCheckedShoppingItems();
      setListStatus(`Cleared ${removed} purchased item(s) and added them to inventory.`);
    } catch (error) {
      console.error("Failed to clear purchased items", error);
      setListStatus("Could not clear checked items.");
    }
  };

  const clearEntireList = async () => {
    if (items.length === 0) {
      setListStatus("The shopping list is already empty.");
      return;
    }
    if (!window.confirm("Clear the entire shopping list? Checked items will be added to pantry first.")) {
      return;
    }
    try {
      const result = await clearAllShoppingItems();
      setListStatus(
        result.restocked > 0
          ? `Cleared ${result.removed} item(s). ${result.restocked} checked item(s) were added to inventory.`
          : `Cleared ${result.removed} item(s) from the shopping list.`
      );
    } catch (error) {
      console.error("Failed to clear shopping list", error);
      setListStatus("Could not clear the shopping list.");
    }
  };

  const checkedCount = items.filter((item) => item.checked).length;
  const hasSmartPlanSuggestions = Boolean(
    smartPlan &&
      ((smartPlan.staples?.length ?? 0) > 0 ||
        (smartPlan.unlocks?.length ?? 0) > 0 ||
        (smartPlan.waste_prevention?.length ?? 0) > 0)
  );

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100 p-8">
      <div className="max-w-2xl mx-auto">
        <h1 className="text-3xl font-bold text-sky-400 mb-2">🛒 Shopping List</h1>
        <p className="text-gray-400 mb-6">
          Add items here — they&apos;ll appear on the kitchen hub instantly
        </p>
        <p className="text-xs text-gray-500 mb-6">
          Checked items stay on the list until you clear them, so you can change your mind before they are added to inventory.
        </p>

        <form onSubmit={handleBarcodeScan} className="mb-5 bg-sky-950/20 border border-sky-900/50 rounded-xl p-4 flex flex-col sm:flex-row gap-3 items-end">
          <div className="flex-1 w-full">
            <label className="block text-xs font-medium text-sky-300 mb-1">Barcode Scanner</label>
            <input
              ref={scanInputRef}
              autoFocus
              inputMode="numeric"
              pattern="[0-9]*"
              type="text"
              placeholder="Scan UPC to add to shopping list..."
              value={scanUpc}
              onChange={(e) => setScanUpc(e.target.value.replace(/\D/g, ""))}
              className="w-full px-4 py-2 rounded-lg bg-gray-900 border border-sky-800 text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-sky-500"
            />
            {scanStatus && (
              <p className={`mt-2 text-xs ${scanStatus.includes("Added") || scanStatus.includes("Updated") ? "text-emerald-400" : "text-sky-300"}`}>
                {scanStatus}
              </p>
            )}
          </div>
          <button
            type="submit"
            disabled={scanBusy || !scanUpc.trim()}
            className="w-full sm:w-auto bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white font-medium px-4 py-2 rounded-lg transition"
          >
            {scanBusy ? "Adding..." : "Scan Add"}
          </button>
        </form>

        <div className="flex flex-col gap-4 mb-6">
          <div className="flex flex-col sm:flex-row gap-4">
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

          <div className="flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
            <div className="text-xs text-gray-500">
              {checkedCount > 0 ? `${checkedCount} item(s) checked and waiting to be cleared.` : "No items are checked yet."}
            </div>
            <div className="flex flex-col sm:flex-row gap-3">
              <button
                onClick={clearPurchased}
                type="button"
                className="px-4 py-2 rounded-lg border border-emerald-800 bg-emerald-950/30 text-emerald-300 hover:bg-emerald-900/40 transition-colors"
              >
                Clear Purchased
              </button>
              <button
                onClick={clearEntireList}
                type="button"
                className="px-4 py-2 rounded-lg border border-red-900/60 bg-red-950/20 text-red-300 hover:bg-red-900/30 transition-colors"
              >
                Clear Entire List
              </button>
            </div>
          </div>
        </div>

        {(planStatus || listStatus) && (
          <div className="mb-6 space-y-2">
            {planStatus && (
              <p className={`text-sm ${planStatus.toLowerCase().includes("failed") || planStatus.toLowerCase().includes("could not") ? "text-red-400" : "text-indigo-300"}`}>
                {planStatus}
              </p>
            )}
            {listStatus && (
              <p className={`text-sm ${listStatus.toLowerCase().includes("could not") ? "text-red-400" : "text-emerald-300"}`}>
                {listStatus}
              </p>
            )}
          </div>
        )}

        {smartPlan && (
          <div className="mb-8 p-5 bg-indigo-950/20 border border-indigo-900/50 rounded-xl space-y-4 animate-in fade-in slide-in-from-top-4">
            <div className="flex justify-between items-center">
              <h2 className="text-lg font-bold text-indigo-400">Suggested Smart Plan</h2>
              <button onClick={() => setSmartPlan(null)} className="text-indigo-500 hover:text-indigo-300 text-sm">Dismiss</button>
            </div>
            
            {!hasSmartPlanSuggestions && (
              <p className="text-sm text-gray-400">
                The latest plan ran successfully, but there are no restock, recipe unlock, or waste-prevention suggestions right now.
              </p>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
               <div>
                  <h3 className="font-bold text-xs uppercase text-gray-500 mb-2">Restock Staples</h3>
                  <ul className="space-y-2">
                    {smartPlan.staples?.map((i, idx) => (
                      <li key={idx} className="flex justify-between items-center text-sm bg-gray-900 p-2 rounded">
                        <span className="text-gray-300 truncate pr-2">{i.item}</span>
                        <button onClick={()=>addPlanItem(i.item)} className="bg-sky-900/50 hover:bg-sky-800 text-sky-400 px-2 py-1 rounded text-xs">+</button>
                      </li>
                    ))}
                    {(smartPlan.staples?.length ?? 0) === 0 && (
                      <li className="text-sm text-gray-500 bg-gray-900/50 p-2 rounded">Nothing to restock right now.</li>
                    )}
                  </ul>
               </div>
               <div>
                  <h3 className="font-bold text-xs uppercase text-gray-500 mb-2">High Impact Unlocks</h3>
                  <ul className="space-y-2">
                    {smartPlan.unlocks?.map((i, idx) => (
                      <li key={idx} className="flex justify-between items-center text-sm bg-gray-900 p-2 rounded">
                        <span className="text-emerald-400 truncate pr-2">{i.item}</span>
                        <button onClick={()=>addPlanItem(i.item)} className="bg-sky-900/50 hover:bg-sky-800 text-sky-400 px-2 py-1 rounded text-xs">+</button>
                      </li>
                    ))}
                    {(smartPlan.unlocks?.length ?? 0) === 0 && (
                      <li className="text-sm text-gray-500 bg-gray-900/50 p-2 rounded">No unlock suggestions yet.</li>
                    )}
                  </ul>
               </div>
               <div>
                  <h3 className="font-bold text-xs uppercase text-gray-500 mb-2">Waste Prevention</h3>
                  <ul className="space-y-2">
                    {smartPlan.waste_prevention?.map((i, idx) => (
                      <li key={idx} className="flex justify-between items-center text-sm bg-gray-900 p-2 rounded">
                        <span className="text-amber-400 truncate pr-2" title={i.reason}>{i.item}</span>
                        <button className="bg-amber-900/30 text-amber-500 px-2 py-1 rounded text-[10px]" disabled>Cook It!</button>
                      </li>
                    ))}
                    {(smartPlan.waste_prevention?.length ?? 0) === 0 && (
                      <li className="text-sm text-gray-500 bg-gray-900/50 p-2 rounded">No waste-prevention items right now.</li>
                    )}
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
                <span className="text-xs text-gray-500">
                  {item.quantity || 1}{item.unit && item.unit !== "unit" ? ` ${item.unit}` : ""}
                </span>
                {item.addedBy === "analytics-auto" && (
                  <span className="ml-auto text-xs text-amber-400">📊 auto</span>
                )}
                {item.addedBy === "barcode-scan" && (
                  <span className="ml-auto text-xs text-sky-400">scan</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
