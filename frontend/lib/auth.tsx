"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { ApiError, getAuthSession } from "@/lib/api";
import type { AuthSession } from "@/lib/api";

type AuthStatus = "checking" | "authenticated" | "unauthenticated";

type AuthContextValue = {
  status: AuthStatus;
  username: string;
  error: string;
  setAuthenticated: (username: string) => void;
  clearSession: (error?: string) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);
let initialSessionRequest: Promise<AuthSession> | null = null;

function getInitialSession() {
  if (!initialSessionRequest) {
    initialSessionRequest = getAuthSession().finally(() => {
      initialSessionRequest = null;
    });
  }
  return initialSessionRequest;
}

export function AuthProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [username, setUsername] = useState("");
  const [error, setError] = useState("");

  const setAuthenticated = useCallback((nextUsername: string) => {
    setUsername(nextUsername);
    setError("");
    setStatus("authenticated");
  }, []);

  const clearSession = useCallback((message = "") => {
    setUsername("");
    setError(message);
    setStatus("unauthenticated");
  }, []);

  useEffect(() => {
    let active = true;
    const handleUnauthorized = () => {
      if (active) clearSession("Your session expired. Sign in again to continue.");
    };
    window.addEventListener("personal-life-os:unauthorized", handleUnauthorized);

    getInitialSession()
      .then((session) => {
        if (active) setAuthenticated(session.username);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        if (cause instanceof ApiError && cause.status === 401) {
          clearSession();
        } else {
          clearSession(
            cause instanceof Error
              ? `Could not verify your secure session: ${cause.message}`
              : "Could not verify your secure session.",
          );
        }
      });

    return () => {
      active = false;
      window.removeEventListener("personal-life-os:unauthorized", handleUnauthorized);
    };
  }, [clearSession, setAuthenticated]);

  const value = useMemo(
    () => ({ status, username, error, setAuthenticated, clearSession }),
    [status, username, error, setAuthenticated, clearSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider.");
  return context;
}
