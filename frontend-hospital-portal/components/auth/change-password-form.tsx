"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import type { Staff } from "@/lib/api-types";
import { passwordProblem } from "@/components/auth/signup-form";
import { signOutNow } from "@/components/session/session-context";
import {
  ErrorState,
  FormError,
  LoadingState,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";

/**
 * Change password. Also the way out of a temporary password: the backend
 * refuses everything else until it is changed (403 "Change your temporary
 * password to continue."), and the portal sends such staff here.
 */
export function ChangePasswordForm() {
  const me = useApi<Staff>("auth/me");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  if (me.loading && !me.data) return <LoadingState />;
  if (me.error || !me.data) {
    return <ErrorState message={me.error?.message ?? "Could not load your account."} onRetry={me.reload} />;
  }
  const forced = me.data.must_change_password;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const problem = passwordProblem(next);
    if (problem) return setError(problem);
    if (next !== confirm) return setError("The new passwords do not match.");
    if (next === current) return setError("Choose a password different from the current one.");
    setBusy(true);
    setError(null);
    try {
      await apiFetch("auth/password", {
        method: "POST",
        body: { current_password: current, new_password: next },
      });
      setDone(true);
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change the password.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div data-testid="password-changed" className="space-y-4">
        <p className="rounded-2xl bg-emerald-50 p-4 text-sm text-emerald-900">
          Your password is changed. Other devices signed in to your account have been signed out.
        </p>
        <Link href="/" className={`${primaryButtonClass} w-full py-2.5`}>
          Continue to the portal
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      {forced && (
        <p data-testid="must-change-password" className="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          You signed in with a temporary password. Choose your own password to continue.
        </p>
      )}
      <p className="text-xs text-slate-500">
        Signed in as <strong>{me.data.email}</strong>
      </p>
      <div>
        <label htmlFor="current-password" className={labelClass}>
          {forced ? "Temporary password" : "Current password"}
        </label>
        <input
          id="current-password"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="new-password" className={labelClass}>
          New password
        </label>
        <input
          id="new-password"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(event) => setNext(event.target.value)}
          className={inputClass}
        />
        <p className="mt-1 text-[11px] text-slate-400">At least 10 characters, with upper and lower case letters.</p>
      </div>
      <div>
        <label htmlFor="confirm-password" className={labelClass}>
          Confirm new password
        </label>
        <input
          id="confirm-password"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
          className={inputClass}
        />
      </div>
      <FormError message={error} />
      <div className="flex flex-col gap-2 sm:flex-row">
        <button type="submit" disabled={busy || !current || !next} className={`${primaryButtonClass} flex-1 py-2.5`}>
          {busy ? "Saving…" : "Change password"}
        </button>
        {forced ? (
          <button type="button" onClick={() => void signOutNow()} className={`${secondaryButtonClass} flex-1 py-2.5`}>
            Sign out
          </button>
        ) : (
          <Link href="/" className={`${secondaryButtonClass} flex-1 py-2.5`}>
            Cancel
          </Link>
        )}
      </div>
    </form>
  );
}
