"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { loginWithEmail, registerWithEmail } from "@/lib/auth";
import { useAuth } from "@/components/auth-provider";

type AuthField = "displayName" | "householdName" | "email" | "password";

const TOUCH_NUMBER_ROW = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"];
const TOUCH_ALPHA_ROWS = [
  ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
  ["z", "x", "c", "v", "b", "n", "m"],
];
const TOUCH_SYMBOL_ROW = ["@", ".", "_", "-", "+"];

export default function HomePage() {
  const { user, loading } = useAuth();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [householdName, setHouseholdName] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [activeField, setActiveField] = useState<AuthField>("email");

  const activeFieldOrder = useMemo<AuthField[]>(
    () => (mode === "signin" ? ["email", "password"] : ["displayName", "householdName", "email", "password"]),
    [mode]
  );

  useEffect(() => {
    setActiveField((current) => (activeFieldOrder.includes(current) ? current : activeFieldOrder[0]));
  }, [activeFieldOrder]);

  const getFieldValue = (field: AuthField) => {
    if (field === "displayName") return displayName;
    if (field === "householdName") return householdName;
    if (field === "email") return email;
    return password;
  };

  const setFieldValue = (field: AuthField, value: string) => {
    if (field === "displayName") {
      setDisplayName(value);
      return;
    }
    if (field === "householdName") {
      setHouseholdName(value);
      return;
    }
    if (field === "email") {
      setEmail(value);
      return;
    }
    setPassword(value);
  };

  const appendTouchKey = (key: string) => {
    setFieldValue(activeField, `${getFieldValue(activeField)}${key}`);
  };

  const backspaceTouchKey = () => {
    setFieldValue(activeField, getFieldValue(activeField).slice(0, -1));
  };

  const clearTouchField = () => {
    setFieldValue(activeField, "");
  };

  const focusNextField = () => {
    const currentIndex = activeFieldOrder.indexOf(activeField);
    const nextIndex = (currentIndex + 1) % activeFieldOrder.length;
    setActiveField(activeFieldOrder[nextIndex]);
  };

  const activeFieldLabel =
    activeField === "displayName"
      ? "Your name"
      : activeField === "householdName"
        ? "Household name"
        : activeField === "email"
          ? "Email"
          : "Password";

  const activeFieldValue = getFieldValue(activeField);
  const activeFieldPreview =
    activeField === "password" && activeFieldValue
      ? "•".repeat(activeFieldValue.length)
      : activeFieldValue;

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
      <main className="min-h-screen bg-gray-950 text-gray-100 flex items-center justify-center p-4 md:p-6">
        <div className="w-full max-w-6xl grid gap-4 lg:gap-6 lg:grid-cols-[1.15fr_0.85fr] items-start">
          <section className="rounded-2xl border border-gray-800 bg-gray-900 p-4 md:p-5 shadow-xl">
            <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h1 className="text-2xl md:text-3xl font-extrabold text-emerald-400">Smart Pantry Hub</h1>
                <p className="text-sm text-gray-400 mt-1">Touch keyboard for kiosk sign-in.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={clearTouchField}
                  className="rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm font-medium text-gray-300 hover:bg-gray-700"
                >
                  Clear
                </button>
                <button
                  type="button"
                  onClick={focusNextField}
                  className="rounded border border-emerald-800 bg-emerald-950/30 px-3 py-2 text-sm font-medium text-emerald-300 hover:bg-emerald-900/30"
                >
                  Next
                </button>
              </div>
            </div>

            <div className="mb-3 rounded-xl border border-gray-800 bg-gray-950/70 px-3 py-3">
              <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{activeFieldLabel}</p>
              <p className="mt-2 min-h-7 text-sm text-gray-200 break-all">
                {activeFieldPreview || <span className="text-gray-500">Tap keys to enter text…</span>}
              </p>
            </div>

            <div className="space-y-1.5">
              <div className="flex flex-wrap justify-center gap-1.5">
                {TOUCH_NUMBER_ROW.map((key) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => appendTouchKey(key)}
                    className="min-w-[42px] rounded-lg border border-gray-700 bg-gray-800 px-2.5 py-2.5 text-sm md:text-base font-medium text-gray-100 hover:bg-gray-700 active:bg-gray-600"
                  >
                    {key}
                  </button>
                ))}
              </div>
              {TOUCH_ALPHA_ROWS.map((row, index) => (
                <div key={index} className="flex flex-wrap justify-center gap-1.5">
                  {row.map((key) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => appendTouchKey(key)}
                      className="min-w-[42px] rounded-lg border border-gray-700 bg-gray-800 px-3 py-2.5 text-sm md:text-base font-medium text-gray-100 hover:bg-gray-700 active:bg-gray-600"
                    >
                      {key}
                    </button>
                  ))}
                </div>
              ))}
              <div className="flex flex-wrap justify-center gap-1.5">
                {TOUCH_SYMBOL_ROW.map((key) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => appendTouchKey(key)}
                    className="min-w-[54px] rounded-lg border border-gray-700 bg-gray-800 px-3 py-2.5 text-sm md:text-base font-medium text-gray-100 hover:bg-gray-700 active:bg-gray-600"
                  >
                    {key}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => appendTouchKey(".com")}
                  className="min-w-[76px] rounded-lg border border-gray-700 bg-gray-800 px-3 py-2.5 text-sm md:text-base font-medium text-gray-100 hover:bg-gray-700 active:bg-gray-600"
                >
                  .com
                </button>
              </div>
              <div className="flex flex-wrap justify-center gap-1.5">
                {(activeField === "displayName" || activeField === "householdName") && (
                  <button
                    type="button"
                    onClick={() => appendTouchKey(" ")}
                    className="min-w-[140px] rounded-lg border border-gray-700 bg-gray-800 px-4 py-2.5 text-sm md:text-base font-medium text-gray-100 hover:bg-gray-700 active:bg-gray-600"
                  >
                    Space
                  </button>
                )}
                <button
                  type="button"
                  onClick={backspaceTouchKey}
                  className="min-w-[120px] rounded-lg border border-amber-900/60 bg-amber-950/30 px-4 py-2.5 text-sm md:text-base font-medium text-amber-200 hover:bg-amber-900/30 active:bg-amber-900/50"
                >
                  Backspace
                </button>
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-gray-800 bg-gray-900 p-4 md:p-5 shadow-xl">
            <div className="flex gap-2 mb-4">
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
                      onFocus={() => setActiveField("displayName")}
                      onClick={() => setActiveField("displayName")}
                      onChange={(e) => setDisplayName(e.target.value)}
                      className={`w-full rounded-lg border bg-gray-950 px-4 py-3 text-gray-100 focus:outline-none focus:ring-2 focus:ring-emerald-500 ${activeField === "displayName" ? "border-emerald-500" : "border-gray-700"}`}
                      placeholder="Luke"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-sm text-gray-300">Household name</span>
                    <input
                      value={householdName}
                      onFocus={() => setActiveField("householdName")}
                      onClick={() => setActiveField("householdName")}
                      onChange={(e) => setHouseholdName(e.target.value)}
                      className={`w-full rounded-lg border bg-gray-950 px-4 py-3 text-gray-100 focus:outline-none focus:ring-2 focus:ring-emerald-500 ${activeField === "householdName" ? "border-emerald-500" : "border-gray-700"}`}
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
                  onFocus={() => setActiveField("email")}
                  onClick={() => setActiveField("email")}
                  onChange={(e) => setEmail(e.target.value)}
                  className={`w-full rounded-lg border bg-gray-950 px-4 py-3 text-gray-100 focus:outline-none focus:ring-2 focus:ring-emerald-500 ${activeField === "email" ? "border-emerald-500" : "border-gray-700"}`}
                  placeholder="you@example.com"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm text-gray-300">Password</span>
                <input
                  type="password"
                  value={password}
                  onFocus={() => setActiveField("password")}
                  onClick={() => setActiveField("password")}
                  onChange={(e) => setPassword(e.target.value)}
                  className={`w-full rounded-lg border bg-gray-950 px-4 py-3 text-gray-100 focus:outline-none focus:ring-2 focus:ring-emerald-500 ${activeField === "password" ? "border-emerald-500" : "border-gray-700"}`}
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
