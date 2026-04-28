"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { loginWithEmail, registerWithEmail } from "@/lib/auth";
import { useAuth } from "@/components/auth-provider";

export default function HomePage() {
  const { user, loading } = useAuth();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [householdName, setHouseholdName] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim() || !password.trim()) {
      setStatus("Email and password are required.");
      return;
    }

    setBusy(true);
    setStatus("");
    try {
      if (mode === "signin") {
        await loginWithEmail(email.trim(), password);
      } else {
        await registerWithEmail({
          email: email.trim(),
          password,
          displayName: displayName.trim(),
          householdName: householdName.trim(),
        });
      }
    } catch (error) {
      console.error("Auth failed", error);
      setStatus(error instanceof Error ? error.message : "Could not sign in right now.");
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <main className="min-h-screen bg-gray-950 text-gray-100 flex items-center justify-center p-8">
        <p className="text-gray-500">Loading account...</p>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="min-h-screen bg-gray-950 text-gray-100 flex items-center justify-center p-8">
        <div className="w-full max-w-5xl grid gap-8 lg:grid-cols-[1.2fr_0.8fr] items-start">
          <section className="space-y-6">
            <div>
              <h1 className="text-4xl font-extrabold text-emerald-400 mb-3">
                Smart Pantry Hub
              </h1>
              <p className="max-w-xl text-gray-400 text-lg">
                Each household gets its own pantry, shopping list, recipes, and analytics inside one Firebase project.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {[
                ["Separate pantry data", "Keep each account or household scoped cleanly."],
                ["Shared backend worker", "Recipes and smart plans stay in one analytics service."],
                ["Mobile-friendly structure", "The same Firebase model can support a future phone app."],
              ].map(([title, body]) => (
                <div key={title} className="rounded-xl border border-gray-800 bg-gray-900 p-4">
                  <h2 className="text-sm font-semibold text-gray-100 mb-2">{title}</h2>
                  <p className="text-sm text-gray-400">{body}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-2xl border border-gray-800 bg-gray-900 p-6 shadow-xl">
            <div className="flex gap-2 mb-5">
              <button
                type="button"
                onClick={() => setMode("signin")}
                className={`rounded px-4 py-2 text-sm font-medium ${mode === "signin" ? "bg-emerald-600 text-white" : "bg-gray-800 text-gray-300"}`}
              >
                Sign In
              </button>
              <button
                type="button"
                onClick={() => setMode("signup")}
                className={`rounded px-4 py-2 text-sm font-medium ${mode === "signup" ? "bg-emerald-600 text-white" : "bg-gray-800 text-gray-300"}`}
              >
                Create Account
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              {mode === "signup" && (
                <>
                  <label className="block">
                    <span className="mb-1 block text-sm text-gray-300">Your name</span>
                    <input
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      className="w-full rounded-lg border border-gray-700 bg-gray-950 px-4 py-3 text-gray-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                      placeholder="Luke"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-sm text-gray-300">Household name</span>
                    <input
                      value={householdName}
                      onChange={(e) => setHouseholdName(e.target.value)}
                      className="w-full rounded-lg border border-gray-700 bg-gray-950 px-4 py-3 text-gray-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                      placeholder="Main Kitchen"
                    />
                  </label>
                </>
              )}
              <label className="block">
                <span className="mb-1 block text-sm text-gray-300">Email</span>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full rounded-lg border border-gray-700 bg-gray-950 px-4 py-3 text-gray-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  placeholder="you@example.com"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm text-gray-300">Password</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-lg border border-gray-700 bg-gray-950 px-4 py-3 text-gray-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  placeholder="At least 6 characters"
                />
              </label>
              {status && (
                <p className="text-sm text-amber-300">{status}</p>
              )}
              <button
                type="submit"
                disabled={busy}
                className="w-full rounded-lg bg-emerald-600 px-4 py-3 font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-60"
              >
                {busy ? "Working..." : mode === "signin" ? "Sign In" : "Create Account"}
              </button>
            </form>
          </section>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100 flex flex-col items-center justify-center p-8">
      <h1 className="text-4xl font-extrabold text-emerald-400 mb-3">
        {user.householdName}
      </h1>
      <p className="text-gray-400 max-w-md text-center mb-10">
        Signed in as {user.displayName}. Manage your pantry, shopping list, and kitchen analytics for this household.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-lg">
        <Link
          href="/inventory"
          className="flex flex-col items-center gap-2 p-6 rounded-xl border border-emerald-800 bg-gray-900 hover:bg-gray-800 transition-all group"
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
          className="flex flex-col items-center gap-2 p-6 rounded-xl border border-sky-800 bg-gray-900 hover:bg-gray-800 transition-all group"
        >
          <span className="text-4xl">🛒</span>
          <span className="text-lg font-semibold text-sky-400 group-hover:text-sky-300">
            Shopping List
          </span>
          <span className="text-sm text-gray-500 text-center">
            Add items remotely and keep this household in sync
          </span>
        </Link>
      </div>
    </main>
  );
}
