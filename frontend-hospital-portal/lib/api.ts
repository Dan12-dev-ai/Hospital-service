"use client";

import { hardNavigate } from "@/lib/navigation";
import { useCallback, useEffect, useState } from "react";

/** An error answer from the portal's API (the backend's {"error": "..."} shape). */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const TEMPORARY_PASSWORD = "Change your temporary password to continue.";

function messageOf(body: unknown, status: number): { message: string; code?: string } {
  if (typeof body === "object" && body !== null) {
    const record = body as Record<string, unknown>;
    if (typeof record.error === "string") {
      return {
        message: record.error,
        code: typeof record.error_code === "string" ? record.error_code : undefined,
      };
    }
  }
  return { message: status >= 500 ? "Something went wrong. Try again." : `Request failed (${status}).` };
}

/** Where the browser goes when the session is gone. */
function goToLogin() {
  const here = `${window.location.pathname}${window.location.search}`;
  const next = here && here !== "/" ? `?next=${encodeURIComponent(here)}` : "";
  hardNavigate(`/login${next}`);
}

/**
 * Calls the portal's own `/api/...` (the BFF). The session cookie goes with
 * it automatically; this code never sees the token.
 */
export async function apiFetch<T>(
  path: string,
  init: { method?: "GET" | "POST" | "PATCH" | "DELETE"; body?: unknown; redirectOn401?: boolean } = {}
): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: string | undefined;
  if (method !== "GET" && method !== "DELETE") {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.body ?? {});
  }
  let response: Response;
  try {
    response = await fetch(`/api/${path.replace(/^\/+/, "")}`, {
      method,
      headers,
      body,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Cannot reach the portal. Check your connection.", 0);
  }
  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!response.ok) {
    const { message, code } = messageOf(parsed, response.status);
    if (response.status === 401 && init.redirectOn401 !== false) goToLogin();
    if (response.status === 403 && message === TEMPORARY_PASSWORD) {
      hardNavigate("/account/password");
    }
    throw new ApiError(message, response.status, code);
  }
  return parsed as T;
}

type Loaded<T> = { key: string; data: T | null; error: ApiError | null };

/**
 * Loads `path` (null: nothing to load) and reloads it on demand. `loading`
 * is true until the answer for the current path arrives.
 */
export function useApi<T>(path: string | null) {
  const [version, setVersion] = useState(0);
  const [loaded, setLoaded] = useState<Loaded<T> | null>(null);
  const key = path === null ? null : `${version}:${path}`;

  useEffect(() => {
    if (path === null || key === null) return;
    let cancelled = false;
    apiFetch<T>(path).then(
      (data) => {
        if (!cancelled) setLoaded({ key, data, error: null });
      },
      (error: unknown) => {
        if (cancelled) return;
        const apiError = error instanceof ApiError ? error : new ApiError("Something went wrong.", 0);
        setLoaded({ key, data: null, error: apiError });
      }
    );
    return () => {
      cancelled = true;
    };
  }, [path, key]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  const current = loaded !== null && loaded.key === key ? loaded : null;
  // Keep showing the previous data while a reload or a new filter loads.
  const data = current?.data ?? (loaded?.error ? null : loaded?.data ?? null);
  return {
    data,
    error: current?.error ?? null,
    loading: key !== null && current === null,
    reload,
  };
}
