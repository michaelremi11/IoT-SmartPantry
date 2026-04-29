"use client";

import { useAuth } from "@/components/auth-provider";
import { ThemeMode, usePreferences } from "@/components/preferences-provider";

function PreferenceToggle({
  checked,
  onChange,
  yesLabel = "On",
  noLabel = "Off",
}: {
  checked: boolean;
  onChange: () => void;
  yesLabel?: string;
  noLabel?: string;
}) {
  return (
    <button
      type="button"
      onClick={onChange}
      aria-pressed={checked}
      className={`relative inline-flex h-10 w-24 items-center rounded-full border transition-colors ${
        checked ? "border-emerald-500 bg-emerald-500/90" : "border-gray-700 bg-gray-800"
      }`}
    >
      <span className={`absolute left-3 text-xs font-semibold ${checked ? "text-gray-950" : "text-gray-400"}`}>
        {yesLabel}
      </span>
      <span className={`absolute right-3 text-xs font-semibold ${checked ? "text-gray-900/40" : "text-gray-200"}`}>
        {noLabel}
      </span>
      <span
        className={`absolute top-1 h-8 w-8 rounded-full bg-white shadow-sm transition-transform ${
          checked ? "translate-x-[52px]" : "translate-x-1"
        }`}
      />
    </button>
  );
}

function ThemeOption({
  value,
  active,
  title,
  description,
  onSelect,
}: {
  value: ThemeMode;
  active: boolean;
  title: string;
  description: string;
  onSelect: (value: ThemeMode) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(value)}
      className={`rounded-xl border p-4 text-left transition ${
        active
          ? "border-emerald-500 bg-emerald-500/10 ring-1 ring-emerald-500/30"
          : "border-gray-800 bg-gray-900/60 hover:bg-gray-900"
      }`}
    >
      <div className="text-sm font-semibold text-gray-100">{title}</div>
      <p className="mt-1 text-sm text-gray-400">{description}</p>
    </button>
  );
}

export default function SettingsPage() {
  const { user } = useAuth();
  const { theme, setTheme, soundEnabled, setSoundEnabled, ready } = usePreferences();

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100 p-6 md:p-8">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
        <section className="rounded-2xl border border-gray-800 bg-gray-900/80 p-6 shadow-sm">
          <h1 className="text-3xl font-bold text-emerald-400">Settings</h1>
          <p className="mt-2 max-w-2xl text-sm text-gray-400">
            Adjust the app theme and a few local device preferences. These settings stay on this browser and do not
            change pantry data for the rest of the household.
          </p>
          {user ? (
            <p className="mt-3 text-xs text-gray-500">
              Signed in as {user.displayName} for <span className="text-gray-300">{user.householdName}</span>.
            </p>
          ) : (
            <p className="mt-3 text-xs text-gray-500">You can adjust appearance before signing in.</p>
          )}
        </section>

        <section className="rounded-2xl border border-gray-800 bg-gray-900/70 p-6 shadow-sm">
          <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
            <div>
              <h2 className="text-xl font-semibold text-gray-100">Appearance</h2>
              <p className="text-sm text-gray-400">Switch between dark and light mode for the dashboard.</p>
            </div>
            <div className="text-xs uppercase tracking-wide text-gray-500">{ready ? `${theme} mode active` : "Loading theme"}</div>
          </div>

          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <ThemeOption
              value="dark"
              active={theme === "dark"}
              title="Dark Mode"
              description="Best fit for the kiosk-style pantry dashboard and lower-glare rooms."
              onSelect={setTheme}
            />
            <ThemeOption
              value="light"
              active={theme === "light"}
              title="Light Mode"
              description="A brighter layout for daylight use, demos, and touch-first browsing."
              onSelect={setTheme}
            />
          </div>
        </section>

        <section className="rounded-2xl border border-gray-800 bg-gray-900/70 p-6 shadow-sm">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-xl font-semibold text-gray-100">Touch Preferences</h2>
              <p className="text-sm text-gray-400">
                This keeps the old settings-branch sound option, ready for future scanner and kiosk feedback.
              </p>
            </div>
            <PreferenceToggle checked={soundEnabled} onChange={() => setSoundEnabled(!soundEnabled)} />
          </div>
          <p className="mt-4 text-xs text-gray-500">
            Sound effects are currently a saved preference only. No pantry behavior changes when you toggle it yet.
          </p>
        </section>
      </div>
    </main>
  );
}
