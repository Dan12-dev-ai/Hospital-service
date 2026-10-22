"use client";

import { hardNavigate } from "@/lib/navigation";
import { useState, type FormEvent } from "react";
import Link from "next/link";
import { ApiError, apiFetch } from "@/lib/api";
import type { Staff } from "@/lib/api-types";
import { FormError, inputClass, labelClass, primaryButtonClass } from "@/components/common/states";

/** Only paths inside the portal (never another site) are followed after sign-in. */
export function safeNext(value: string | null, origin = "https://portal.invalid"): string {
  // Browsers drop tabs and newlines inside URLs ("/<TAB>/evil.com" becomes
  // "//evil.com"), so any control character or backslash is refused, and
  // the result must stay on this site once resolved.
  if (!value || !value.startsWith("/") || /[\u0000-\u001f\u007f\\]/.test(value)) return "/";
  let url: URL;
  try {
    url = new URL(value, origin);
  } catch {
    return "/";
  }
  if (url.origin !== origin) return "/";
  if (url.pathname.startsWith("/login") || url.pathname.startsWith("/signup")) return "/";
  return `${url.pathname}${url.search}${url.hash}`;
}

export function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { staff } = await apiFetch<{ staff: Staff }>("auth/login", {
        method: "POST",
        body: { email: email.trim(), password },
        redirectOn401: false,
      });
      const next = safeNext(new URLSearchParams(window.location.search).get("next"));
      // A hospital still applying goes back to its application.
      if (staff.must_change_password) return hardNavigate("/account/password");
      // A hospital still applying goes back to its application (or its status).
      hardNavigate(staff.hospital?.locked ? "/onboarding" : next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <div>
        <label htmlFor="login-email" className={labelClass}>
          Email
        </label>
        <input
          id="login-email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="login-password" className={labelClass}>
          Password
        </label>
        <input
          id="login-password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className={inputClass}
        />
      </div>
      <FormError message={error} />
      <button type="submit" disabled={busy || !email || !password} className={`${primaryButtonClass} w-full py-2.5`}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
      <p className="text-center text-xs text-slate-500">
        New to Endod?{" "}
        <Link href="/onboarding" className="font-semibold text-pine-green hover:underline">
          Apply to join Endod
        </Link>
      </p>
    </form>
  );
}
