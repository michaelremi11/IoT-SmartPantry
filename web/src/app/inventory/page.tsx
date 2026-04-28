// web/src/app/inventory/page.tsx
"use client";

import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import {
  addBarcodeToPantry,
  addPantryItem,
  allocateIngredientAcrossPantry,
  clearAllRecipes,
  cookRecipeFromFirestore,
  deleteRecipe,
  FirestoreTimestamp,
  getComparableItemQuantity,
  getItemQuantityValue,
  getRecipeIngredientComparableAmount,
  getRecipeIngredientList,
  PantryItem,
  performPantryAction,
  RecipeItem,
  recipeIngredientToText,
  requestRecipeDiscovery,
  subscribeAnalyticsSummary,
  subscribePantry,
  subscribeRecipes,
} from "@/lib/firestore";
import { useAuth } from "@/components/auth-provider";
import { BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, LineChart, Line } from 'recharts';

type RecipeFilter = "time" | "match" | "none";
type WasteReportRow = {
  item_id: string;
  cooked: number;
  discarded: number;
  waste_rate: number;
  suggestion: string;
};
type HistoricalScorePoint = { date: string; score: number };
type PopularCategory = { category: string; count: number };
type RecipeUnlock = { ingredient: string; unlocks: number };
type LiveStatus = {
  temperature?: number;
  humidity?: number;
  comfort_score?: number;
};
type LiveTrend = { trend?: string };
type RiskState = {
  high_risk_active?: boolean;
  min_humidity_5m?: number;
};
type BuySignal = {
  item_id: string;
  name: string;
  signal: "BUY_MORE" | "BUY_LESS" | string;
  reason: string;
  score: number;
  days_until_empty?: number | null;
  expiry_ratio?: number | null;
};
type ManualField = "name" | "category" | "amount" | "unit";
const RECIPE_FILTER_OPTIONS: Array<{ value: RecipeFilter; label: string }> = [
  { value: "none", label: "Default" },
  { value: "match", label: "Best Match" },
  { value: "time", label: "Fastest" },
];
const INGREDIENTS_DB: Record<string, { category: string; unit: string }> = {
  "Milk": { category: "liquid", unit: "fl oz" },
  "Water": { category: "liquid", unit: "fl oz" },
  "Olive Oil": { category: "sauce", unit: "fl oz" },
  "Vegetable Oil": { category: "sauce", unit: "fl oz" },
  "Flour": { category: "carb", unit: "cups" },
  "Sugar": { category: "misc", unit: "cups" },
  "Rice": { category: "carb", unit: "grams" },
  "Chicken Breast": { category: "protein", unit: "grams" },
  "Ground Beef": { category: "protein", unit: "grams" },
  "Spinach": { category: "veg", unit: "grams" },
  "Lettuce": { category: "veg", unit: "grams" },
  "Tomato": { category: "veg", unit: "unit" },
  "Avocado": { category: "veg", unit: "unit" },
  "Bread": { category: "carb", unit: "slices" },
  "Eggs": { category: "protein", unit: "unit" },
  "Salt": { category: "misc", unit: "tsp" },
  "Pepper": { category: "misc", unit: "tsp" },
};
const TOUCH_ALPHA_ROWS = [
  ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
  ["z", "x", "c", "v", "b", "n", "m"],
];
const TOUCH_NUMERIC_ROWS = [
  ["1", "2", "3"],
  ["4", "5", "6"],
  ["7", "8", "9"],
  ["0", "."],
];
const MANUAL_FIELD_ORDER: ManualField[] = ["name", "category", "amount", "unit"];

export default function InventoryPage() {
  const { user, loading: authLoading } = useAuth();
  const householdId = user?.householdId || "";
  const [activeTab, setActiveTab] = useState<"pantry" | "recipes" | "sustainability" | "analytics">("pantry");

  // Pantry State
  const [items, setItems] = useState<PantryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sustainabilityScore, setSustainabilityScore] = useState<number | null>(null);

  // New Analytics & Sustainability States
  const [wasteReport, setWasteReport] = useState<WasteReportRow[]>([]);
  const [historicalScore, setHistoricalScore] = useState<HistoricalScorePoint[]>([]);
  const [popCategories, setPopCategories] = useState<PopularCategory[]>([]);
  const [missions, setMissions] = useState<string[]>([]);
  const [unlocks, setUnlocks] = useState<RecipeUnlock[]>([]);
  const [buySignals, setBuySignals] = useState<BuySignal[]>([]);

  // Live Status State
  const [liveStatus, setLiveStatus] = useState<LiveStatus | null>(null);
  const [liveTrend, setLiveTrend] = useState<LiveTrend | null>(null);
  const [riskState, setRiskState] = useState<RiskState | null>(null);

  // Manual Entry Form State
  const [manualName, setManualName] = useState("");
  const [manualCat, setManualCat] = useState("");
  const [manualExpiry, setManualExpiry] = useState("");
  const [manualAmount, setManualAmount] = useState("1");
  const [manualUnit, setManualUnit] = useState("unit");
  const [activeManualField, setActiveManualField] = useState<ManualField | null>(null);
  const [scanUpc, setScanUpc] = useState("");
  const [scanStatus, setScanStatus] = useState("");
  const [scanBusy, setScanBusy] = useState(false);
  const scanInputRef = useRef<HTMLInputElement | null>(null);

  const applyManualName = (val: string) => {
    setManualName(val);
    const match = Object.keys(INGREDIENTS_DB).find(k => k.toLowerCase() === val.toLowerCase());
    if (match) {
      setManualCat(INGREDIENTS_DB[match].category);
      setManualUnit(INGREDIENTS_DB[match].unit);
    }
  };

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    applyManualName(e.target.value);
  };

  // Recipes State
  const [recipesList, setRecipesList] = useState<RecipeItem[]>([]);
  const [loadingRecipes, setLoadingRecipes] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [recipeMaintenanceBusy, setRecipeMaintenanceBusy] = useState(false);
  const [recipeStatus, setRecipeStatus] = useState("");
  const [expandedRecipe, setExpandedRecipe] = useState<string | null>(null);
  
  // Recipe Filters
  const [recipeFilter, setRecipeFilter] = useState<RecipeFilter>("none");

  useEffect(() => {
    if (!householdId) {
      if (!authLoading) {
        setLoading(false);
        setLoadingRecipes(false);
      }
      return;
    }

    const unsubPantry = subscribePantry(householdId, (data) => {
      setItems(data);
      setLoading(false);
    });
    
    const unsubRecipes = subscribeRecipes(householdId, (data) => {
      setRecipesList(data);
      setLoadingRecipes(false);
    });
    const unsubSustainability = subscribeAnalyticsSummary<{ sustainability_score?: number }>(householdId, "sustainability", (data) => {
      setSustainabilityScore(data?.sustainability_score ?? 100);
    });
    const unsubWaste = subscribeAnalyticsSummary<{ waste_report?: WasteReportRow[] }>(householdId, "wasteReport", (data) => {
      setWasteReport(data?.waste_report ?? []);
    });
    const unsubHistorical = subscribeAnalyticsSummary<{ trend?: HistoricalScorePoint[] }>(householdId, "historicalSustainability", (data) => {
      setHistoricalScore(data?.trend ?? []);
    });
    const unsubCategories = subscribeAnalyticsSummary<{ categories?: PopularCategory[] }>(householdId, "popularCategories", (data) => {
      setPopCategories(data?.categories ?? []);
    });
    const unsubMissions = subscribeAnalyticsSummary<{ missions?: string[] }>(householdId, "missions", (data) => {
      setMissions(data?.missions ?? []);
    });
    const unsubUnlocks = subscribeAnalyticsSummary<{ high_impact_purchases?: RecipeUnlock[] }>(householdId, "recipeUnlocks", (data) => {
      setUnlocks(data?.high_impact_purchases ?? []);
    });
    const unsubBuySignals = subscribeAnalyticsSummary<{ signals?: BuySignal[] }>(householdId, "buySignals", (data) => {
      setBuySignals(data?.signals ?? []);
    });
    const unsubLiveStatus = subscribeAnalyticsSummary<LiveStatus>(householdId, "liveStatus", setLiveStatus);
    const unsubLiveTrend = subscribeAnalyticsSummary<LiveTrend>(householdId, "liveTrend", setLiveTrend);
    const unsubRisk = subscribeAnalyticsSummary<RiskState>(householdId, "risk", setRiskState);

    return () => {
      unsubPantry();
      unsubRecipes();
      unsubSustainability();
      unsubWaste();
      unsubHistorical();
      unsubCategories();
      unsubMissions();
      unsubUnlocks();
      unsubBuySignals();
      unsubLiveStatus();
      unsubLiveTrend();
      unsubRisk();
    };
  }, [authLoading, householdId]);

  const handleAction = async (itemId: string, actionType: "cooked" | "discarded") => {
    try {
      await performPantryAction(itemId, actionType, householdId);
    } catch (e) {
      console.error("Action failed", e);
      window.alert("Could not update this pantry item. Please try again.");
    }
  };

  // --- PANTRY LOGIC ---
  const handleManualAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualName) return;
    try {
      await addPantryItem({
        householdId,
        name: manualName,
        category: manualCat || "misc",
        quantity: parseFloat(manualAmount) || 1,
        unit: manualUnit || "unit",
        expiryDate: manualExpiry || null,
      });
      setManualName("");
      setManualCat("");
      setManualExpiry("");
      setManualAmount("1");
      setManualUnit("unit");
    } catch (e) {
      console.error("Add failed", e);
      window.alert("Could not add this pantry item. Please try again.");
    }
  };

  const handleBarcodeScan = async (e: React.FormEvent) => {
    e.preventDefault();
    const upc = scanUpc.trim();
    if (!upc || scanBusy) return;

    setScanBusy(true);
    setScanStatus(`Looking up UPC ${upc}...`);
    try {
      const result = await addBarcodeToPantry(upc, householdId);
      const verb = result.action === "restocked" ? "Restocked" : "Added";
      setScanStatus(`${verb}: ${result.name} (+${result.quantity_added} ${result.unit})`);
      setScanUpc("");
    } catch (error) {
      console.error("Barcode scan failed", error);
      setScanStatus(error instanceof Error ? error.message : "Could not add that UPC.");
    } finally {
      setScanBusy(false);
      requestAnimationFrame(() => scanInputRef.current?.focus());
    }
  };

  const handleCookRecipe = async (recipeId: string) => {
    try {
      await cookRecipeFromFirestore(recipeId, householdId);
      alert("Recipe ingredients deducted from pantry!");
    } catch (e) {
      console.error("Cook recipe failed", e);
      window.alert("Could not cook this recipe. Please try again.");
    }
  };

  const handleDeleteRecipe = async (recipeId: string, title: string) => {
    if (!window.confirm(`Remove "${title}" from your recipe book?`)) {
      return;
    }
    try {
      setRecipeMaintenanceBusy(true);
      await deleteRecipe(recipeId);
      setRecipeStatus(`Removed "${title}" from your recipe book.`);
      if (expandedRecipe === recipeId) {
        setExpandedRecipe(null);
      }
    } catch (e) {
      console.error("Delete recipe failed", e);
      setRecipeStatus("Could not remove that recipe. Please try again.");
    } finally {
      setRecipeMaintenanceBusy(false);
    }
  };

  const handleClearRecipes = async () => {
    if (recipesList.length === 0) {
      setRecipeStatus("There are no recipes to clear.");
      return;
    }
    if (!window.confirm(`Clear all ${recipesList.length} saved recipe(s)?`)) {
      return;
    }
    try {
      setRecipeMaintenanceBusy(true);
      const removed = await clearAllRecipes(householdId);
      setExpandedRecipe(null);
      setRecipeStatus(`Cleared ${removed} recipe(s) from your recipe book.`);
    } catch (e) {
      console.error("Clear recipes failed", e);
      setRecipeStatus("Could not clear the recipe book. Please try again.");
    } finally {
      setRecipeMaintenanceBusy(false);
    }
  };

  const filtered = useMemo(() => {
    return items.filter((i) =>
      i.name.toLowerCase().includes(search.toLowerCase())
    );
  }, [items, search]);

  const groupedItems = useMemo(() => {
    const groups: Record<string, PantryItem[]> = {
      veg: [], fruit: [], protein: [], carb: [], sauce: [], misc: []
    };
    filtered.forEach(item => {
      const cat = (item.category || "").toLowerCase();
      if (cat.includes("veg")) groups.veg.push(item);
      else if (cat.includes("fruit")) groups.fruit.push(item);
      else if (cat.includes("protein") || cat.includes("meat")) groups.protein.push(item);
      else if (cat.includes("carb") || cat.includes("grain") || cat.includes("bread")) groups.carb.push(item);
      else if (cat.includes("sauce") || cat.includes("condiment")) groups.sauce.push(item);
      else groups.misc.push(item);
    });
    return groups;
  }, [filtered]);

  const updateManualFieldValue = (field: ManualField, value: string) => {
    if (field === "name") {
      applyManualName(value);
      return;
    }
    if (field === "category") {
      setManualCat(value);
      return;
    }
    if (field === "amount") {
      setManualAmount(value);
      return;
    }
    setManualUnit(value);
  };

  const getManualFieldValue = (field: ManualField | null) => {
    if (field === "name") return manualName;
    if (field === "category") return manualCat;
    if (field === "amount") return manualAmount;
    if (field === "unit") return manualUnit;
    return "";
  };

  const appendTouchKey = (key: string) => {
    if (!activeManualField) return;
    const current = getManualFieldValue(activeManualField);
    if (activeManualField === "amount" && key === "." && current.includes(".")) {
      return;
    }
    updateManualFieldValue(activeManualField, `${current}${key}`);
  };

  const backspaceTouchKey = () => {
    if (!activeManualField) return;
    const current = getManualFieldValue(activeManualField);
    updateManualFieldValue(activeManualField, current.slice(0, -1));
  };

  const clearTouchField = () => {
    if (!activeManualField) return;
    updateManualFieldValue(activeManualField, "");
  };

  const focusNextManualField = () => {
    if (!activeManualField) {
      setActiveManualField("name");
      return;
    }
    const index = MANUAL_FIELD_ORDER.indexOf(activeManualField);
    setActiveManualField(MANUAL_FIELD_ORDER[(index + 1) % MANUAL_FIELD_ORDER.length]);
  };

  const expiringSoon = (expiry?: string) => {
    if (!expiry) return false;
    const diff = (new Date(expiry).getTime() - Date.now()) / 86400000;
    return diff >= 0 && diff <= 3;
  };

  // --- RECIPE LOGIC ---
  const discoverNewRecipes = async () => {
    setDiscovering(true);
    try {
      await requestRecipeDiscovery(householdId);
    } catch (e) {
      console.error("Discovery failed", e);
      window.alert("Could not queue recipe discovery. Please try again.");
    } finally {
      setDiscovering(false);
    }
  };

  // Visual Pantry Matching Engine
  const availablePantry = useMemo(
    () =>
      items.map((item) => ({
        ...item,
        quantity: getItemQuantityValue(item),
      })),
    [items]
  );
  
  const isIngredientHighRisk = (ingredientText: string) => {
    const lower = ingredientText.toLowerCase();
    return lower.includes("spinach") || lower.includes("bread") || lower.includes("lettuce") || lower.includes("tomato") || lower.includes("avocado") || lower.includes("fruit") || lower.includes("avocado toast");
  };
  
  const getRecipeVisualState = useCallback((recipeIngs: RecipeItem["ingredients"]) => {
    let matchedCount = 0;
    let highRiskMatchCount = 0;
    const missing: string[] = [];
    const normalizedIngredients = getRecipeIngredientList(recipeIngs);
    const pantryPool = availablePantry.map((item) => ({
      ...item,
      quantity: getComparableItemQuantity(item),
      amount: getComparableItemQuantity(item),
    }));

    normalizedIngredients.forEach((ingredient) => {
      const amountNeeded = getRecipeIngredientComparableAmount(ingredient);
      const allocation = allocateIngredientAcrossPantry(ingredient, amountNeeded, pantryPool);
      const ingredientText = recipeIngredientToText(ingredient);

      if (allocation.satisfied) {
        matchedCount++;
        allocation.allocations.forEach(({ item, used }) => {
          item.quantity = Math.max(0, getComparableItemQuantity(item) - used);
          item.amount = item.quantity;
        });
        if (riskState?.high_risk_active && isIngredientHighRisk(ingredientText)) {
          highRiskMatchCount++;
        }
      } else {
        missing.push(ingredientText);
      }
    });
    
    const missingCount = normalizedIngredients.length - matchedCount;
    const is100Percent = missingCount === 0;
    const isAlmost = missingCount === 1 || missingCount === 2;
    const isUnavailable = missingCount > 2;

    return { matchedCount, missing, missingCount, is100Percent, isAlmost, isUnavailable, highRiskMatchCount };
  }, [availablePantry, riskState]);

  // Filter & Sorting logic
  const parseTime = (timeStr?: string) => {
    if (!timeStr) return 9999;
    let mins = 0;
    if (timeStr.includes("hour")) {
      const match = timeStr.match(/(\d+)\s*hour/);
      if (match) mins += parseInt(match[1], 10) * 60;
    }
    if (timeStr.includes("minute")) {
      const match = timeStr.match(/(\d+)\s*minute/);
      if (match) mins += parseInt(match[1], 10);
    }
    return mins || 9999;
  };

  const sortedRecipes = useMemo(() => {
    const list = [...recipesList];
    if (riskState?.high_risk_active) {
      list.sort((a, b) => {
        const aRisk = getRecipeVisualState(a.ingredients).highRiskMatchCount;
        const bRisk = getRecipeVisualState(b.ingredients).highRiskMatchCount;
        if (bRisk !== aRisk) return bRisk - aRisk;
        // Fallback to time/match
        if (recipeFilter === "time") return parseTime(a.estimated_time) - parseTime(b.estimated_time);
        return getRecipeVisualState(b.ingredients).matchedCount - getRecipeVisualState(a.ingredients).matchedCount;
      });
    } else if (recipeFilter === "time") {
      list.sort((a, b) => parseTime(a.estimated_time) - parseTime(b.estimated_time));
    } else if (recipeFilter === "match") {
      list.sort((a, b) => getRecipeVisualState(b.ingredients).matchedCount - getRecipeVisualState(a.ingredients).matchedCount);
    }
    return list;
  }, [recipesList, recipeFilter, riskState, getRecipeVisualState]);

  const isNewBadge = (timestamp?: FirestoreTimestamp) => {
    if (!timestamp || !timestamp.seconds) return false;
    const diffHours = (Date.now() / 1000 - timestamp.seconds) / 3600;
    return diffHours < 24;
  };

  if (authLoading) {
    return (
      <main className="min-h-screen bg-gray-950 text-gray-100 flex items-center justify-center p-8">
        <p className="text-gray-500">Loading account...</p>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="min-h-screen bg-gray-950 text-gray-100 flex items-center justify-center p-8">
        <p className="text-gray-500">Sign in on the home page to open your pantry.</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100 p-8 transition-colors duration-500 relative">
      <div className="max-w-5xl mx-auto space-y-8">
        {/* Toast Notification for Risk */}
        {riskState?.high_risk_active && (
          <div className="fixed bottom-6 right-6 bg-red-950/90 border border-red-500 text-red-50 p-5 rounded-2xl shadow-[0_10px_40px_rgba(239,68,68,0.3)] z-50 animate-in slide-in-from-bottom-5 fade-in duration-500 max-w-sm backdrop-blur-md">
            <h3 className="flex items-center gap-2 font-bold text-lg mb-1">
              <span className="text-xl">⚠️</span> Environment Alert
            </h3>
            <p className="text-sm text-red-200">
              Humidity is high ({riskState.min_humidity_5m}%). Your recipes have been reordered to prioritize cooking High Risk items (like Spinach and Bread) today to avoid waste! 🥬🥖
            </p>
          </div>
        )}

        {/* Header Section */}
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h1 className="text-3xl font-bold text-emerald-400 mb-2">
              Kitchen Hub
            </h1>
            <p className="text-gray-400">Manage your pantry and plan meals smartly.</p>
          </div>
          
          <div className="flex flex-col sm:flex-row gap-4">
            {/* Live Widget */}
            {liveStatus && liveStatus.temperature !== undefined && (
              <div className="bg-gray-900 border border-gray-700 p-3 rounded-xl min-w-[200px] shadow-sm">
                <div className="text-xs text-gray-400 uppercase font-semibold mb-2">Live Kitchen Status</div>
                <div className="flex justify-between items-center text-sm mb-1">
                  <span className="text-gray-300">Temp:</span>
                  <span className="font-bold text-emerald-400">{liveStatus.temperature}°C</span>
                </div>
                <div className="flex justify-between items-center text-sm mb-1">
                  <span className="text-gray-300">Humidity:</span>
                  <span className="font-bold text-emerald-400">{liveStatus.humidity}%</span>
                </div>
                {liveStatus.comfort_score !== undefined && (
                  <div className="flex justify-between items-center text-sm pt-1 border-t border-gray-800 mt-1">
                    <span className="text-gray-300">Comfort:</span>
                    <span className={`font-bold ${liveStatus.comfort_score > 80 ? 'text-emerald-400' : 'text-amber-400'}`}>
                      {liveStatus.comfort_score}/100
                    </span>
                  </div>
                )}
                {liveTrend && liveTrend.trend && (
                  <div className="text-[10px] text-gray-500 mt-2 text-right">
                    {liveTrend.trend}
                  </div>
                )}
              </div>
            )}
            
            {/* Sustainability */}
            {sustainabilityScore !== null && (
              <div className="bg-gray-900 border border-gray-700 p-4 rounded-xl text-center min-w-[120px] shadow-sm">
                <div className="text-xs text-gray-400 uppercase font-semibold">Sustainability</div>
                <div className={`text-2xl font-bold ${sustainabilityScore > 80 ? 'text-emerald-400' : sustainabilityScore > 50 ? 'text-amber-400' : 'text-red-400'}`}>
                  {sustainabilityScore}%
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="flex border-b border-gray-800 space-x-6 overflow-x-auto pb-1 hide-scrollbar">
          <button
            onClick={() => setActiveTab("pantry")}
            className={`whitespace-nowrap pb-3 border-b-2 font-medium transition-colors ${activeTab === "pantry" ? "border-emerald-500 text-emerald-400" : "border-transparent text-gray-400 hover:text-gray-200"}`}
          >
            My Pantry
          </button>
          <button
            onClick={() => setActiveTab("recipes")}
            className={`whitespace-nowrap pb-3 border-b-2 font-medium transition-colors ${activeTab === "recipes" ? "border-emerald-500 text-emerald-400" : "border-transparent text-gray-400 hover:text-gray-200"}`}
          >
            Recipe Book
          </button>
          <button
            onClick={() => setActiveTab("sustainability")}
            className={`whitespace-nowrap pb-3 border-b-2 font-medium transition-colors ${activeTab === "sustainability" ? "border-emerald-500 text-emerald-400" : "border-transparent text-gray-400 hover:text-gray-200"}`}
          >
            Sustainability 🌍
          </button>
          <button
            onClick={() => setActiveTab("analytics")}
            className={`whitespace-nowrap pb-3 border-b-2 font-medium transition-colors ${activeTab === "analytics" ? "border-emerald-500 text-emerald-400" : "border-transparent text-gray-400 hover:text-gray-200"}`}
          >
            Analytics 📈
          </button>
        </div>

        {activeTab === "pantry" && (
          <div className="space-y-8 animate-in fade-in flex flex-col">
            {/* Barcode Scan */}
            <form onSubmit={handleBarcodeScan} className="bg-sky-950/20 border border-sky-900/50 rounded-xl p-5 flex flex-col md:flex-row gap-4 items-end shadow-md">
              <div className="flex-1 w-full">
                <label className="block text-xs font-medium text-sky-300 mb-1">Barcode Scanner</label>
                <input
                  ref={scanInputRef}
                  autoFocus
                  inputMode="numeric"
                  pattern="[0-9]*"
                  type="text"
                  placeholder="Scan UPC..."
                  value={scanUpc}
                  onChange={(e) => setScanUpc(e.target.value.replace(/\D/g, ""))}
                  className="w-full bg-gray-900 border border-sky-800 rounded p-3 text-sm focus:ring-2 focus:ring-sky-500 outline-none"
                />
                {scanStatus && (
                  <p className={`mt-2 text-xs ${scanStatus.includes("Added") || scanStatus.includes("Restocked") ? "text-emerald-400" : "text-sky-300"}`}>
                    {scanStatus}
                  </p>
                )}
              </div>
              <button
                type="submit"
                disabled={scanBusy || !scanUpc.trim()}
                className="w-full md:w-auto bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white font-medium px-6 py-3 rounded transition-colors text-sm shadow"
              >
                {scanBusy ? "Adding..." : "Scan Add"}
              </button>
            </form>

            {/* Manual Entry Form */}
            <form onSubmit={handleManualAdd} className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex flex-col md:flex-row gap-4 items-end shadow-md flex-wrap">
              <div className="flex-1 min-w-[200px]">
                <label className="block text-xs font-medium text-gray-400 mb-1">Item Name</label>
                <input required type="text" placeholder="e.g. Olive Oil" value={manualName} onFocus={() => setActiveManualField("name")} onClick={() => setActiveManualField("name")} onChange={handleNameChange} className={`w-full bg-gray-800 border rounded p-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none ${activeManualField === "name" ? "border-emerald-500" : "border-gray-700"}`} />
              </div>
              <div className="flex-1 min-w-[120px]">
                <label className="block text-xs font-medium text-gray-400 mb-1">Category</label>
                <input type="text" placeholder="e.g. sauce" value={manualCat} onFocus={() => setActiveManualField("category")} onClick={() => setActiveManualField("category")} onChange={e => setManualCat(e.target.value)} className={`w-full bg-gray-800 border rounded p-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none ${activeManualField === "category" ? "border-emerald-500" : "border-gray-700"}`} />
              </div>
              <div className="flex-1 min-w-[100px]">
                <label className="block text-xs font-medium text-gray-400 mb-1">Amount</label>
                <input type="number" step="0.01" min="0" value={manualAmount} onFocus={() => setActiveManualField("amount")} onClick={() => setActiveManualField("amount")} onChange={e => setManualAmount(e.target.value)} className={`w-full bg-gray-800 border rounded p-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none ${activeManualField === "amount" ? "border-emerald-500" : "border-gray-700"}`} />
              </div>
              <div className="flex-1 min-w-[80px]">
                <label className="block text-xs font-medium text-gray-400 mb-1">Unit</label>
                <input type="text" value={manualUnit} onFocus={() => setActiveManualField("unit")} onClick={() => setActiveManualField("unit")} onChange={e => setManualUnit(e.target.value)} className={`w-full bg-gray-800 border rounded p-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none ${activeManualField === "unit" ? "border-emerald-500" : "border-gray-700"}`} />
              </div>
              <div className="flex-1 min-w-[150px]">
                <label className="block text-xs font-medium text-gray-400 mb-1">Expiry Date</label>
                <input type="date" value={manualExpiry} onChange={e => setManualExpiry(e.target.value)} className="w-full bg-gray-800 border border-gray-700 rounded p-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none text-gray-300" />
              </div>
              <button type="submit" className="w-full md:w-auto bg-emerald-600 hover:bg-emerald-500 text-white font-medium px-6 py-2 rounded transition-colors text-sm shadow">
                + Add Item
              </button>
            </form>

            {activeManualField && (
              <div className="rounded-xl border border-emerald-900/50 bg-gray-900/90 p-4 shadow-md">
                <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-sm font-semibold text-emerald-300">On-Screen Keyboard</p>
                    <p className="text-xs text-gray-500">
                      Editing {activeManualField === "name" ? "Item Name" : activeManualField === "category" ? "Category" : activeManualField === "amount" ? "Amount" : "Unit"}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={clearTouchField} className="rounded border border-gray-700 bg-gray-800 px-3 py-1 text-xs text-gray-300 hover:bg-gray-700">
                      Clear
                    </button>
                    <button type="button" onClick={focusNextManualField} className="rounded border border-emerald-800 bg-emerald-950/30 px-3 py-1 text-xs text-emerald-300 hover:bg-emerald-900/30">
                      Next
                    </button>
                    <button type="button" onClick={() => setActiveManualField(null)} className="rounded border border-gray-700 bg-gray-800 px-3 py-1 text-xs text-gray-300 hover:bg-gray-700">
                      Done
                    </button>
                  </div>
                </div>

                <div className="mb-4 rounded-lg border border-gray-800 bg-gray-950/60 px-3 py-2 text-sm text-gray-200">
                  {getManualFieldValue(activeManualField) || <span className="text-gray-500">Tap keys to enter text...</span>}
                </div>

                <div className="space-y-2">
                  {(activeManualField === "amount" ? TOUCH_NUMERIC_ROWS : TOUCH_ALPHA_ROWS).map((row, index) => (
                    <div key={index} className="flex flex-wrap justify-center gap-2">
                      {row.map((key) => (
                        <button
                          key={key}
                          type="button"
                          onClick={() => appendTouchKey(key)}
                          className="min-w-[52px] rounded-lg border border-gray-700 bg-gray-800 px-4 py-3 text-base font-medium text-gray-100 hover:bg-gray-700 active:bg-gray-600"
                        >
                          {key}
                        </button>
                      ))}
                    </div>
                  ))}

                  {activeManualField !== "amount" ? (
                    <div className="flex flex-wrap justify-center gap-2">
                      <button type="button" onClick={() => appendTouchKey(" ")} className="min-w-[140px] rounded-lg border border-gray-700 bg-gray-800 px-4 py-3 text-base font-medium text-gray-100 hover:bg-gray-700 active:bg-gray-600">
                        Space
                      </button>
                      <button type="button" onClick={backspaceTouchKey} className="min-w-[100px] rounded-lg border border-amber-900/60 bg-amber-950/30 px-4 py-3 text-base font-medium text-amber-200 hover:bg-amber-900/30 active:bg-amber-900/50">
                        Backspace
                      </button>
                    </div>
                  ) : (
                    <div className="flex flex-wrap justify-center gap-2">
                      <button type="button" onClick={backspaceTouchKey} className="min-w-[140px] rounded-lg border border-amber-900/60 bg-amber-950/30 px-4 py-3 text-base font-medium text-amber-200 hover:bg-amber-900/30 active:bg-amber-900/50">
                        Backspace
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Search */}
            <input type="search" placeholder="Search items..." value={search} onChange={(e) => setSearch(e.target.value)} className="w-full px-4 py-3 rounded-xl bg-gray-900 border border-gray-800 text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-emerald-500 shadow-sm" />

            {/* Display Inventory Grouped */}
            {loading ? (
              <p className="text-gray-500 animate-pulse">Loading inventory…</p>
            ) : filtered.length === 0 ? (
              <p className="text-gray-500 text-center py-10 bg-gray-900/50 rounded-xl">No items found in your pantry.</p>
            ) : (
              <div className="space-y-6">
                {Object.entries(groupedItems).map(([catName, catItems]) => {
                  if (catItems.length === 0) return null;
                  return (
                    <div key={catName} className="overflow-hidden rounded-xl border border-gray-800 bg-gray-900/50 shadow-sm">
                      <div className="bg-gray-800/80 px-4 py-3 font-semibold text-emerald-400 capitalize border-b border-gray-700">
                        {catName}
                      </div>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead className="bg-gray-900/40 text-gray-400 uppercase text-xs">
                            <tr>
                              {["Name", "Qty", "Unit", "Expires", "Actions"].map((h) => <th key={h} className="px-4 py-3 text-left">{h}</th>)}
                            </tr>
                          </thead>
                          <tbody>
                            {catItems.map((item) => (
                              <tr key={item.id} className="border-t border-gray-800 hover:bg-gray-800/60 transition-colors">
                                <td className="px-4 py-3 font-medium text-gray-200">{item.name}</td>
                                <td className="px-4 py-3">{item.quantity}</td>
                                <td className="px-4 py-3 text-gray-500">{item.unit}</td>
                                <td className="px-4 py-3">
                                  <span className={expiringSoon(item.expiryDate) ? "text-amber-400 font-semibold" : "text-gray-500"}>
                                    {item.expiryDate || "—"}{expiringSoon(item.expiryDate) && " ⚠️"}
                                  </span>
                                 </td>
                                <td className="px-4 py-3 flex gap-2">
                                  <button onClick={() => handleAction(item.id, "cooked")} className="px-3 py-1 bg-emerald-900/50 text-emerald-400 hover:bg-emerald-800/60 rounded text-xs font-semibold border border-emerald-800 transition-colors">Cook</button>
                                  <button onClick={() => handleAction(item.id, "discarded")} className="px-3 py-1 bg-red-900/50 text-red-400 hover:bg-red-800/60 rounded text-xs font-semibold border border-red-800 transition-colors">Discard</button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {activeTab === "recipes" && (
          <div className="space-y-6 animate-in fade-in flex flex-col">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center bg-gray-900/50 p-6 rounded-xl border border-gray-800 gap-4 shadow-sm">
              <div>
                <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
                  <span>Your Recipes</span>
                  {discovering && <span className="text-xs bg-emerald-900/60 text-emerald-300 px-2 py-0.5 rounded-full animate-pulse border border-emerald-800">Chef is writing...</span>}
                </h2>
                <p className="text-sm text-gray-400 mt-1">Visually spot what you can make right now based on pantry matches.</p>
                {recipeStatus && (
                  <p className={`text-sm mt-3 ${recipeStatus.toLowerCase().includes("could not") ? "text-red-400" : "text-amber-300"}`}>
                    {recipeStatus}
                  </p>
                )}
              </div>
              <div className="flex flex-col sm:flex-row gap-3">
                <div className="flex flex-wrap gap-2 rounded-lg border border-gray-700 bg-gray-800 p-1 shadow-sm">
                  {RECIPE_FILTER_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setRecipeFilter(option.value)}
                      className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                        recipeFilter === option.value
                          ? "bg-emerald-600 text-white"
                          : "text-gray-300 hover:bg-gray-700"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <button 
                  onClick={discoverNewRecipes}
                  disabled={discovering}
                  className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-medium px-5 py-2.5 rounded-lg transition-colors flex items-center gap-2 shadow"
                >
                  {discovering ? "Thinking..." : "✨ Discover"}
                </button>
                <button
                  onClick={handleClearRecipes}
                  disabled={recipeMaintenanceBusy || recipesList.length === 0}
                  className="bg-red-950/40 hover:bg-red-900/40 disabled:opacity-50 text-red-300 border border-red-900/60 font-medium px-5 py-2.5 rounded-lg transition-colors"
                >
                  Clear Recipes
                </button>
              </div>
            </div>

            {loadingRecipes ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                 {[1,2,3,4,5,6].map(i => <div key={i} className="h-40 bg-gray-900/50 animate-pulse rounded-xl border border-gray-800"></div>)}
              </div>
            ) : sortedRecipes.length === 0 ? (
              <div className="text-center py-12 bg-gray-900/30 rounded-xl border border-gray-800 border-dashed">
                <p className="text-gray-400 text-lg">No recipes in your book yet.</p>
                <p className="text-gray-600 text-sm mt-1">Hit discover to generate some, or run the seed script!</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {sortedRecipes.map((r, index) => {
                  const state = getRecipeVisualState(r.ingredients);
                  // Apply visual logic classes
                  let cardClasses = "transition-all duration-700 ease-in-out border rounded-xl overflow-hidden flex flex-col relative shadow ";
                  
                  if (riskState?.high_risk_active && state.highRiskMatchCount > 0) {
                    cardClasses += "bg-red-950/30 border-red-500/80 shadow-[0_0_15px_rgba(239,68,68,0.2)] ring-1 ring-red-500/30 transform hover:-translate-y-1 ";
                  } else if (state.is100Percent) {
                    cardClasses += "bg-gray-900 border-emerald-500/80 shadow-[0_0_15px_rgba(16,185,129,0.15)] ring-1 ring-emerald-500/20 transform hover:-translate-y-1 ";
                  } else if (state.isAlmost) {
                    cardClasses += "bg-gray-900 border-gray-700 opacity-80 hover:opacity-100 ";
                  } else {
                    cardClasses += "bg-gray-900/40 border-gray-800 opacity-40 hover:opacity-60 scale-[0.98] ";
                  }

                  const isNew = isNewBadge(r.created_at);
                  
                  return (
                    <div key={r.id || index} className={cardClasses}>
                      {riskState?.high_risk_active && state.highRiskMatchCount > 0 ? (
                         <div className="absolute top-0 w-full h-1 bg-gradient-to-r from-red-600 to-red-400" />
                      ) : state.is100Percent ? (
                         <div className="absolute top-0 w-full h-1 bg-gradient-to-r from-emerald-600 to-emerald-400" />
                      ) : null}
                      
                      <div className="p-5 flex-1 z-10 pt-6">
                        <div className="flex justify-between items-start mb-2 gap-2">
                          <h3 className={`font-bold text-lg leading-tight transition-colors duration-500 ${state.is100Percent ? 'text-emerald-50' : 'text-gray-200'}`}>
                            {r.title}
                          </h3>
                          <div className="flex flex-col gap-1 items-end shrink-0">
                            {r.source === "ai-generated" && <span className="bg-emerald-900/60 text-emerald-300 text-[9px] px-2 py-0.5 rounded-full border border-emerald-800 uppercase tracking-widest font-bold">AI Chef</span>}
                            {isNew && <span className="bg-amber-900/60 text-amber-300 text-[9px] px-2 py-0.5 rounded-full border border-amber-800 uppercase tracking-widest font-bold shadow-sm">New</span>}
                          </div>
                        </div>
                        
                        {r.estimated_time && (
                           <div className="text-xs font-semibold text-gray-400 mb-3 flex flex-wrap items-center gap-2">
                             <div className="bg-gray-800 px-2 py-1 rounded text-amber-500/90 shadow-sm">⏱ {r.estimated_time}</div>
                             {riskState?.high_risk_active && state.highRiskMatchCount > 0 ? (
                               <span className="text-red-400 bg-red-900/40 px-2 py-1 rounded border border-red-800/50 font-bold shadow-sm animate-pulse">Save Risk Items 🚨</span>
                             ) : state.is100Percent ? (
                               <span className="text-emerald-400 bg-emerald-900/30 px-2 py-1 rounded border border-emerald-800/30 font-bold shadow-sm animate-pulse-slow">✓ Ready to Cook</span>
                             ) : state.isAlmost ? (
                               <span className="text-amber-400 bg-amber-900/30 px-2 py-1 rounded border border-amber-800/30 font-semibold shadow-sm">Missing {state.missingCount} item{state.missingCount>1?'s':''}</span>
                             ) : (
                               <span className="text-gray-500 bg-gray-800/50 px-2 py-1 rounded border border-gray-700/50">Missing {state.missingCount} items</span>
                             )}
                           </div>
                        )}
                        
                        <p className={`text-xs font-medium leading-relaxed mt-2 transition-colors duration-500 ${state.isUnavailable ? 'text-gray-500' : 'text-gray-400'}`}>
                          {getRecipeIngredientList(r.ingredients).map((ingredient, i) => {
                            const ingredientText = recipeIngredientToText(ingredient);
                            const isMissing = state.missing.includes(ingredientText);
                            return (
                              <span key={i} className={isMissing ? "text-red-400/80 line-through decoration-red-900/50" : (state.is100Percent ? "text-emerald-200" : "")}>
                                {ingredientText}{i < r.ingredients.length - 1 ? " • " : ""}
                              </span>
                            );
                          })}
                        </p>
                      </div>
                      
                      {expandedRecipe === (r.id || String(index)) && (
                        <div className="px-5 pb-4 text-sm text-gray-300 bg-gray-800/60 border-t border-gray-700 pt-4 z-10 shadow-inner">
                          <p className="font-semibold text-gray-200 mb-2">Instructions</p>
                          <ul className="space-y-2 text-gray-400">
                             {r.instructions.split(/(\d+\.)/).filter(Boolean).reduce<string[]>((acc, curr, idx, src) => {
                               if (idx % 2 === 0 && src[idx+1]) { acc.push(curr + src[idx+1]); } else if (idx % 2 === 0) { acc.push(curr); }
                               return acc;
                             }, []).map((s, i) => {
                               // Handle pure numbers or unstructured text gracefully
                               const isStep = /^\d+\./.test(s.trim());
                               return s.trim() ? (
                                 <li key={i} className={isStep ? "flex gap-2" : ""}>
                                   {isStep ? (
                                     <>
                                       <span className="text-emerald-500 font-bold shrink-0">{s.match(/^\d+\./)?.[0]}</span>
                                       <span>{s.replace(/^\d+\./, '').trim()}</span>
                                     </>
                                   ) : (
                                     s.trim()
                                   )}
                                 </li>
                               ) : null;
                             })}
                          </ul>
                        </div>
                      )}
                      
                      <div className={`p-3 border-t mt-auto z-10 transition-colors duration-500 flex gap-2 ${state.is100Percent ? 'bg-emerald-950/20 border-emerald-900/30' : 'bg-gray-950/50 border-gray-800/80'}`}>
                        <button 
                          onClick={() => setExpandedRecipe(expandedRecipe === (r.id || String(index)) ? null : (r.id || String(index)))}
                          className={`flex-1 text-center text-sm font-semibold transition-colors py-1 ${
                            state.is100Percent ? 'text-emerald-400 hover:text-emerald-300' : 'text-gray-400 hover:text-gray-300'
                          }`}
                        >
                          {expandedRecipe === (r.id || String(index)) ? "Collapse" : "View"}
                        </button>
                        <button 
                          onClick={() => r.id && handleCookRecipe(r.id)}
                          disabled={!state.is100Percent || !r.id}
                          className={`flex-1 text-center text-sm border rounded font-semibold transition-colors py-1 ${
                            state.is100Percent ? 'text-white bg-emerald-600 hover:bg-emerald-500 border-none' : 'text-gray-400 bg-gray-800 border-gray-700 opacity-60 cursor-not-allowed'
                          }`}
                        >
                          {state.is100Percent ? "Cook Recipe" : "Need Ingredients"}
                        </button>
                        <button
                          onClick={() => r.id && handleDeleteRecipe(r.id, r.title)}
                          disabled={recipeMaintenanceBusy || !r.id}
                          className="px-3 text-center text-sm border rounded font-semibold transition-colors py-1 text-red-300 bg-red-950/30 border-red-900/60 hover:bg-red-900/40 disabled:opacity-50"
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {activeTab === "sustainability" && (
          <div className="space-y-8 animate-in fade-in flex flex-col">
            <div className="bg-emerald-950/20 border border-emerald-900/50 p-6 rounded-xl">
              <h2 className="text-xl font-bold text-emerald-400 mb-2">High Impact Unlocks 🔓</h2>
              <p className="text-sm text-gray-400 mb-4">These 3 items are missing from your pantry and would unlock the most recipes!</p>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {unlocks.length > 0 ? unlocks.map((u, i) => (
                  <div key={i} className="bg-gray-900 border border-emerald-800/50 p-4 rounded-lg flex items-center justify-between">
                    <span className="font-semibold text-gray-200 capitalize">{u.ingredient}</span>
                    <span className="bg-emerald-900/40 text-emerald-400 text-xs px-2 py-1 rounded">Unlocks {u.unlocks}</span>
                  </div>
                )) : (
                  <p className="text-gray-500">Calculating unlocks...</p>
                )}
              </div>
            </div>

            <div className="bg-gray-900/50 border border-gray-800 p-6 rounded-xl">
              <h2 className="text-xl font-bold text-gray-200 mb-4">Waste vs Consumption</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-900/40 text-gray-400 uppercase text-xs">
                    <tr>
                      <th className="px-4 py-3 text-left">Item</th>
                      <th className="px-4 py-3 text-left">Cooked</th>
                      <th className="px-4 py-3 text-left">Discarded</th>
                      <th className="px-4 py-3 text-left">Waste Rate</th>
                      <th className="px-4 py-3 text-left">Suggestion</th>
                    </tr>
                  </thead>
                  <tbody>
                    {wasteReport.map((w, i) => (
                      <tr key={i} className="border-t border-gray-800">
                        <td className="px-4 py-3 font-medium text-gray-200 capitalize">{w.item_id}</td>
                        <td className="px-4 py-3 text-emerald-400">{w.cooked}</td>
                        <td className="px-4 py-3 text-red-400">{w.discarded}</td>
                        <td className="px-4 py-3">{w.waste_rate}%</td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-1 rounded text-xs px-2 font-semibold ${w.suggestion === 'Buy Less' ? 'bg-amber-900/40 text-amber-400' : 'bg-gray-800 text-gray-400'}`}>
                            {w.suggestion}
                          </span>
                        </td>
                      </tr>
                    ))}
                    {wasteReport.length === 0 && (
                      <tr><td colSpan={5} className="text-center py-4 text-gray-500">No data available yet in the last 30 days.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {activeTab === "analytics" && (
          <div className="space-y-8 animate-in fade-in flex flex-col">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              
              <div className="bg-gray-900/50 border border-gray-800 p-6 rounded-xl flex flex-col">
                 <h2 className="text-lg font-bold text-gray-200 mb-4">Category Popularity</h2>
                 {popCategories.length > 0 ? (
                   <div className="flex-1 w-full h-[250px]">
                     <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={popCategories}>
                          <XAxis dataKey="category" stroke="#9ca3af" fontSize={12} tickLine={false} axisLine={false} />
                          <RechartsTooltip cursor={{fill: 'rgba(255,255,255,0.05)'}} contentStyle={{backgroundColor: '#111827', borderColor: '#374151', borderRadius: '8px'}} />
                          <Bar dataKey="count" fill="#10b981" radius={[4,4,0,0]} />
                        </BarChart>
                     </ResponsiveContainer>
                   </div>
                 ) : (
                   <div className="h-[250px] flex items-center justify-center text-gray-600">No data</div>
                 )}
              </div>

              <div className="bg-gray-900/50 border border-gray-800 p-6 rounded-xl flex flex-col">
                 <h2 className="text-lg font-bold text-gray-200 mb-4">Sustainability Score (7 Days)</h2>
                 {historicalScore.length > 0 ? (
                   <div className="flex-1 w-full h-[250px]">
                     <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={historicalScore}>
                          <XAxis dataKey="date" stroke="#9ca3af" fontSize={10} tickLine={false} axisLine={false} />
                          <YAxis domain={[0, 100]} stroke="#9ca3af" fontSize={12} tickLine={false} axisLine={false} hide />
                          <RechartsTooltip contentStyle={{backgroundColor: '#111827', borderColor: '#374151', borderRadius: '8px'}} />
                          <Line type="monotone" dataKey="score" stroke="#10b981" strokeWidth={3} dot={{r:4, fill:'#10b981', strokeWidth:0}} />
                        </LineChart>
                     </ResponsiveContainer>
                   </div>
                 ) : (
                   <div className="h-[250px] flex items-center justify-center text-gray-600">No data</div>
                 )}
              </div>

            </div>

            <div className="bg-gray-900/50 border border-gray-800 p-6 rounded-xl">
              <h2 className="text-lg font-bold text-gray-200 mb-4">Buy Signals</h2>
              {buySignals.length > 0 ? (
                <div className="space-y-3">
                  {buySignals.map((signal) => (
                    <div key={`${signal.signal}-${signal.item_id}`} className="rounded-lg border border-gray-800 bg-gray-900/70 p-4">
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <div>
                          <div className="font-semibold text-gray-100">{signal.name}</div>
                          <div className="text-sm text-gray-400">{signal.reason}</div>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${
                            signal.signal === "BUY_MORE"
                              ? "bg-emerald-900/40 text-emerald-300"
                              : "bg-amber-900/40 text-amber-300"
                          }`}>
                            {signal.signal === "BUY_MORE" ? "Buy More" : "Buy Less"}
                          </span>
                          <span className="text-xs text-gray-500">Score {signal.score}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-gray-500">No strong buy signals in the current lookback window.</div>
              )}
            </div>

            <div className="bg-indigo-950/20 border border-indigo-900/40 p-6 rounded-xl">
              <h2 className="text-xl font-bold text-indigo-400 mb-4 flex items-center gap-2"><span>🤖</span> AI Weekly Kitchen Missions</h2>
              <ul className="space-y-3">
                {missions.length > 0 ? missions.map((m, i) => (
                  <li key={i} className="flex gap-3 items-start p-3 bg-gray-900/60 border border-indigo-900/20 rounded-lg shadow-sm">
                    <span className="text-indigo-400 font-bold mt-0.5">{i+1}.</span>
                    <span className="text-indigo-100/90">{m}</span>
                  </li>
                )) : (
                  <li className="text-gray-500 animate-pulse">Consulting the AI Chef...</li>
                )}
              </ul>
            </div>
          </div>
        )}

      </div>
    </main>
  );
}
