// web/src/app/page.tsx
// Landing / dashboard home page.
"use client";

import Link from "next/link";
import NextImage from "next/image";
import { X } from "lucide-react";
import { Span } from "next/dist/trace";
// import { useState } from "react";
import { useAppContext } from "../context/context";
import { use } from "react";
// import { useState } from "react";

export default function SettingsPage() {
  const { darkMode, setDarkMode, soundEnabled, setSoundEnabled } = useAppContext();

 
  const text = darkMode
  ? "text-gray-100"
  : "text-gray-500";


// export const metadata = {
//   title: "Smart Pantry Hub — Dashboard",
//   description:
//     "Remotely view your pantry inventory, shopping list and kitchen analytics.",
// };

  return (
    <main className={`min-h-screen ${darkMode ? "bg-gray-950 text-gray-100" : "bg-white text-gray-900"}' flex flex-col items-center justify-center p-8`}>
      <button 
        className="absolute top-6 right-6 p-2 rounded-full text-gray-400 hover:text-emerald-400 hover:bg-gray-900 transition-colors"
        aria-label="Close"
      >
        <Link href="/" className="flex items-center gap-2">
        <X size ={28} className="transition-transform hover:scale-110" />
        </Link>
        
        
        {/* <NextImage
          src="/settings.svg"
          alt="Settings Icon"
          width={28}
          height={28}
        /> */}
      </button>
      <div className= "flex items-center gap-3 mb-3">
         <span className="text-lg font-semibold text-emerald-400 group-hover:text-emerald-300">
            Settings
          </span>
        
      {/* <h1 className="text-4xl font-extrabold text-emerald-400 mb-3">
        Pantry+
      </h1> */}
      </div>
      <p className={`${text} max-w-md text-center mb-10`}>
        Update user preferences
      </p>
      
      <div 
      className="grid grid-cols-1 gap-4 w-full max-w-lg items-center justify-items-center">
         <div className="flex flex-row items-center gap-8">
          <span className="text-lg font-semibold text-emerald-400 group-hover:text-emerald-300">
            Sound Effects:
            {/* <input type="checkbox" className="ml-2" /> */}
          </span>
            <div
            onClick={() => setSoundEnabled(!soundEnabled)}
        className={`relative w-16 h-8 cursor-pointer transition-colors duration-300 border-2 border-emerald-500 ${
      soundEnabled ? "bg-emerald-500" : "bg-gray-700"
    }`}
  >
    {/* Labels */}
    <span className="absolute left-1.5 top-1/2 -translate-y-1/2 text-xs font-bold text-gray-950">Yes</span>
    <span className="absolute right-1.5 top-1/2 -translate-y-1/2 text-xs font-bold text-gray-400">No</span>
    {/* Slider knob */}
    <div
      className={`absolute top w-7 h-7 bg-emerald-500 shadow-md transition-transform duration-300 ${
        soundEnabled ? "translate-x-8" : "translate-x"
      }`}
    />
        </div>
        </div>

        <div className="flex flex-row items-center gap-15">
        <span className="text-lg font-semibold text-emerald-400 group-hover:text-emerald-300">
            Dark Mode:
            {/* <input type="checkbox" className="ml-2" /> */}
          </span>
            <div
            onClick={() => setDarkMode(!darkMode)}
        className={`relative w-16 h-8 cursor-pointer transition-colors duration-300 border-2 border-emerald-500 ${
      darkMode ? "bg-emerald-500" : "bg-gray-700"
    }`}
  >
    {/* Labels */}
    <span className="absolute left-1.5 top-1/2 -translate-y-1/2 text-xs font-bold text-gray-950">Yes</span>
    <span className="absolute right-1.5 top-1/2 -translate-y-1/2 text-xs font-bold text-gray-400">No</span>
    {/* Slider knob */}
    <div
      className={`absolute top w-7 h-7 bg-emerald-500 shadow-md transition-transform duration-300 ${
        darkMode ? "translate-x-8" : "translate-x"
      }`}
    />
        
        </div>
        </div>
      </div>
     
    </main>
  );
}

// const [soundEnabled, setSoundEnabled] = useState(false);


