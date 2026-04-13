// web/src/app/page.tsx
// Landing / dashboard home page.
import Link from "next/link";

export const metadata = {
  title: "Smart Pantry Hub — Dashboard",
  description:
    "Remotely view your pantry inventory, shopping list and kitchen analytics.",
};

export default function HomePage() {
  return (
    <main className="min-h-screen bg-gray-950 text-gray-100 flex flex-col items-center justify-center p-8">
      <h1 className="text-4xl font-extrabold text-emerald-400 mb-3">
        🍃 Smart Pantry Hub
      </h1>
      <p className="text-gray-400 max-w-md text-center mb-10">
        Real-time kitchen intelligence — track inventory, manage your shopping
        list, and catch food waste before it happens.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-lg">
        <Link
          href="/inventory"
          className="flex flex-col items-center gap-2 p-6 rounded-2xl border border-emerald-800
                     bg-gray-900 hover:bg-gray-800 transition-all group"
        >
          <span className="text-4xl">🥦</span>
          <span className="text-lg font-semibold text-emerald-400 group-hover:text-emerald-300">
            Inventory
          </span>
          <span className="text-sm text-gray-500 text-center">
            Browse and search your pantry items in real time
          </span>
        </Link>
        <Link
          href="/shopping"
          className="flex flex-col items-center gap-2 p-6 rounded-2xl border border-sky-800
                     bg-gray-900 hover:bg-gray-800 transition-all group"
        >
          <span className="text-4xl">🛒</span>
          <span className="text-lg font-semibold text-sky-400 group-hover:text-sky-300">
            Shopping List
          </span>
          <span className="text-sm text-gray-500 text-center">
            Add items remotely; they sync instantly to the kitchen hub
          </span>
        </Link>
      </div>
    </main>
  );
}
