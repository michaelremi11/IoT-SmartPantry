// web/src/app/page.tsx
// Landing / dashboard home page.
"use client";

import Link from "next/link";
import NextImage from "next/image";
import { Settings } from "lucide-react";
import { useAppContext } from "./context/context";


export default function HomeClient() {
 
  const { darkMode } = useAppContext();

  const buttons = darkMode 
  ? "bg-gray-900 hover:bg-gray-800"
  : "bg-gray-100 hover:bg-green-100";
  const text = darkMode
  ? "text-gray-100"
  : "text-gray-500";

  return (
    <main className={`min-h-screen ${darkMode ? "bg-gray-950 text-gray-100" : "bg-white text-gray-900"} flex flex-col items-center justify-center p-8`}>
      <button 
        className="absolute top-6 right-6 p-2 rounded-full text-gray-400 hover:text-emerald-400 hover:bg-gray-900 transition-colors"
        aria-label="Settings"
      >
        <Link href="/settings" className="flex items-center gap-2">
        <Settings size ={28} className="transition-transform hover:scale-110" />
        </Link>
        {/* <NextImage
          src="/settings.svg"
          alt="Settings Icon"
          width={28}
          height={28}
        /> */}
      </button>
      <div className= "flex items-center gap-3 mb-3">
        <NextImage
          src="/pantryplusfulllogo.png"
          alt="Pantry+ Logo"
          width={
            172
          }
          height={172}
          priority
        />
      {/* <h1 className="text-4xl font-extrabold text-emerald-400 mb-3">
        Pantry+
      </h1> */}
      </div>
      <p className={`${text} max-w-md text-center mb-10`}>
        Real-time kitchen intelligence — track inventory, manage your shopping
        list, and catch food waste before it happens.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-lg">
        <Link
          href="/inventory"
          className={`flex flex-col items-center gap-2 p-6 rounded-2xl border border-emerald-800 ${buttons} transition-all group`}
        >
          <span className="text-4xl">🥦</span>
          <span className="text-lg font-semibold text-emerald-400 group-hover:text-emerald-300">
            Pantry
          </span>
          <span className={`${text} text-sm text-center`}>
            Add or remove items from your pantry inventory
          </span>
        </Link>
        <Link
          href="/shopping"
          className={`flex flex-col items-center gap-2 p-6 rounded-2xl border border-emerald-800 ${buttons} transition-all group`}
        >
          <span className="text-4xl">🛒</span>
          <span className="text-lg font-semibold text-emerald-400 group-hover:text-emerald-300">
            Shopping List
          </span>
          <span className={`${text} text-sm text-center`}>
            Update your shopping list 
          </span>
        </Link>
      </div>
    </main>
  );
}
