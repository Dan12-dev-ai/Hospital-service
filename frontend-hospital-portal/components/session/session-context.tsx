"use client";

import { hardNavigate } from "@/lib/navigation";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, apiFetch } from "@/lib/api";
import type { Hospital, Role, Staff } from "@/lib/api-types";

type SessionState =
  | { status: "loading" }
  | { status: "error"; error: ApiError }
  | { status: "ready"; staff: Staff; hospital: Hospital };

type SessionValue = SessionState & {
  reload: () => void;
  setHospital: (hospital: Hospital) => void;
  signOut: () => Promise<void>;
};

const SessionContext = createContext<SessionValue | null>(null);

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used within <SessionProvider>");
  return value;
}

/** The signed-in staff member and their hospital, or null while loading. */
export function useSignedIn(): { staff: Staff; hospital: Hospital } | null {
  const session = useSession();
  return session.status === "ready" ? { staff: session.staff, hospital: session.hospital } : null;
}

export function hasRole(staff: Staff | null | undefined, ...roles: Role[]): boolean {
  return Boolean(staff && roles.includes(staff.role));
}

export async function signOutNow() {
  try {
    await apiFetch("auth/logout", { method: "POST", redirectOn401: false });
  } catch {
    // Signed out locally either way: the cookie is cleared by the handler.
  }
  hardNavigate("/login");
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const staff = await apiFetch<Staff>("auth/me");
        // A temporary password first (that page works for every hospital),
        // then a hospital whose application is not approved sees only its
        // application or its status; stay "loading" while the page changes.
        if (staff.must_change_password) {
          hardNavigate("/account/password");
          return;
        }
        if (staff.hospital?.locked) {
          hardNavigate("/onboarding");
          return;
        }
        const hospital = await apiFetch<Hospital>("hospital");
        if (!cancelled) setState({ status: "ready", staff, hospital });
      } catch (error) {
        if (!cancelled) {
          setState({
            status: "error",
            error: error instanceof ApiError ? error : new ApiError("Something went wrong.", 0),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [version]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  const setHospital = useCallback((hospital: Hospital) => {
    setState((current) => (current.status === "ready" ? { ...current, hospital } : current));
  }, []);

  return (
    <SessionContext.Provider value={{ ...state, reload, setHospital, signOut: signOutNow }}>
      {children}
    </SessionContext.Provider>
  );
}
