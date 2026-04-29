"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type ThemeMode = "dark" | "light";

type PreferencesContextValue = {
  theme: ThemeMode;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
  soundEnabled: boolean;
  setSoundEnabled: (enabled: boolean) => void;
  ready: boolean;
};

const THEME_STORAGE_KEY = "smart-pantry-theme";
const SOUND_STORAGE_KEY = "smart-pantry-sound-enabled";

const PreferencesContext = createContext<PreferencesContextValue | null>(null);

function safeStorageGet(key: string): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeStorageSet(key: string, value: string) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Ignore storage failures on kiosk / embedded browsers.
  }
}

function applyTheme(theme: ThemeMode) {
  if (typeof document === "undefined") {
    return;
  }
  document.documentElement.dataset.theme = theme;
}

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeMode>(() =>
    safeStorageGet(THEME_STORAGE_KEY) === "light" ? "light" : "dark"
  );
  const [soundEnabled, setSoundEnabledState] = useState<boolean>(() => safeStorageGet(SOUND_STORAGE_KEY) === "true");

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = useCallback((nextTheme: ThemeMode) => {
    setThemeState(nextTheme);
    safeStorageSet(THEME_STORAGE_KEY, nextTheme);
    applyTheme(nextTheme);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [setTheme, theme]);

  const setSoundEnabled = useCallback((enabled: boolean) => {
    setSoundEnabledState(enabled);
    safeStorageSet(SOUND_STORAGE_KEY, enabled ? "true" : "false");
  }, []);

  const value = useMemo(
    () => ({
      theme,
      setTheme,
      toggleTheme,
      soundEnabled,
      setSoundEnabled,
      ready: true,
    }),
    [setSoundEnabled, setTheme, soundEnabled, theme, toggleTheme]
  );

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences() {
  const context = useContext(PreferencesContext);
  if (!context) {
    throw new Error("usePreferences must be used inside PreferencesProvider");
  }
  return context;
}
