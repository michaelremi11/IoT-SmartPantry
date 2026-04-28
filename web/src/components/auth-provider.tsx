"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { SessionUser, subscribeToSession } from "@/lib/auth";

type AuthContextValue = {
  user: SessionUser | null;
  loading: boolean;
};

const AuthContext = createContext<AuthContextValue>({ user: null, loading: true });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    return subscribeToSession((session, nextLoading) => {
      setUser(session);
      setLoading(nextLoading);
    });
  }, []);

  const value = useMemo(() => ({ user, loading }), [user, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
