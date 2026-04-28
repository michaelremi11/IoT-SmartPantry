"use client";

import Link from "next/link";
import { logout } from "@/lib/auth";
import { useAuth } from "./auth-provider";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();

  return (
    <>
      <header className="sticky top-0 z-50 border-b border-gray-800 bg-gray-950/95 backdrop-blur">
        <nav className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3">
          <Link href="/" className="text-sm font-bold text-emerald-400 hover:text-emerald-300">
            Smart Pantry
          </Link>
          <div className="flex items-center gap-2">
            <Link
              href="/"
              className="rounded px-3 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white"
            >
              Home
            </Link>
            <Link
              href="/inventory"
              className="rounded px-3 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white"
            >
              Inventory
            </Link>
            <Link
              href="/shopping"
              className="rounded px-3 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white"
            >
              Shopping
            </Link>
          </div>
          <div className="flex items-center gap-3">
            {loading ? (
              <span className="text-xs text-gray-500">Loading account...</span>
            ) : user ? (
              <>
                <div className="hidden text-right sm:block">
                  <p className="text-sm font-medium text-gray-200">{user.displayName}</p>
                  <p className="text-xs text-gray-500">{user.householdName}</p>
                </div>
                <button
                  onClick={() => void logout()}
                  className="rounded border border-gray-700 px-3 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white"
                >
                  Sign Out
                </button>
              </>
            ) : (
              <span className="text-xs text-gray-500">Sign in to access your pantry</span>
            )}
          </div>
        </nav>
      </header>
      {children}
    </>
  );
}
