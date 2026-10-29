"use client";

import { useState, type FormEvent } from "react";
import { ApiError, apiFetch } from "@/lib/api";
import type { Staff } from "@/lib/api-types";
import { FormError, inputClass, labelClass, primaryButtonClass } from "@/components/common/states";

const linkButton = "text-xs font-semibold text-pine-green hover:underline";

/**
 * The second step of a sign-in: the 6-digit code from the authenticator app,
 * or one of the recovery codes. A wrong code never signs anyone out; too many
 * pause the account for a while.
 */
export function CodeStep({ onDone, onRestart }: { onDone: (staff: Staff) => void; onRestart: () => void }) {
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { staff } = await apiFetch<{ staff: Staff }>("auth/totp", {
        method: "POST",
        body: recovery ? { recovery_code: code.trim() } : { code: code.replace(/\s/g, "") },
        redirectOn401: false,
      });
      onDone(staff);
    } catch (err) {
      setCode("");
      if (err instanceof ApiError && err.status === 401) return onRestart();
      setError(err instanceof ApiError ? err.message : "Sign-in failed.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate data-testid="code-step">
      <p className="text-xs text-slate-500">
        {recovery
          ? "Enter one of your recovery codes. Each works once."
          : "Enter the 6-digit code from your authenticator app."}
      </p>
      <div>
        <label htmlFor="login-code" className={labelClass}>
          {recovery ? "Recovery code" : "Authentication code"}
        </label>
        <input
          id="login-code"
          autoFocus
          value={code}
          inputMode={recovery ? "text" : "numeric"}
          autoComplete="one-time-code"
          placeholder={recovery ? "xxxx-xxxx-xxxx" : "123456"}
          onChange={(e) => setCode(recovery ? e.target.value.slice(0, 20) : e.target.value.replace(/[^\d ]/g, "").slice(0, 7))}
          className={`${inputClass} font-mono tracking-[0.2em]`}
        />
      </div>
      <FormError message={error} />
      <button type="submit" disabled={busy || !code.trim()} className={`${primaryButtonClass} w-full py-2.5`}>
        {busy ? "Checking…" : "Verify"}
      </button>
      <div className="flex justify-between">
        <button
          type="button"
          className={linkButton}
          onClick={() => {
            setRecovery((value) => !value);
            setCode("");
            setError(null);
          }}
        >
          {recovery ? "Use the authenticator app" : "Use a recovery code"}
        </button>
        <button
          type="button"
          className={linkButton}
          onClick={async () => {
            await apiFetch("auth/logout", { method: "POST", redirectOn401: false }).catch(() => null);
            onRestart();
          }}
        >
          Start again
        </button>
      </div>
    </form>
  );
}
