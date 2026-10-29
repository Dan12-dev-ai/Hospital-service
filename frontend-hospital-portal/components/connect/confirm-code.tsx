"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import {
  FormError,
  Modal,
  dangerButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { ApiError, apiFetch } from "@/lib/api";

/** The backend's answer (app/twofactor.py, REAUTH_REQUIRED) when a fresh code is needed. */
export const REAUTH_REQUIRED = "Confirm it is you: enter a code from your authenticator app.";

export function needsFreshCode(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && error.message === REAUTH_REQUIRED;
}

/**
 * Asks for a fresh code from the admin's authenticator app (re-authentication)
 * before a sensitive change: connecting a system, its credentials or settings,
 * disconnecting it. The code is good for 10 minutes; wrong ones are counted
 * (and pause the account after a few), but never sign anyone out.
 */
export function ConfirmCode({
  title,
  actionLabel,
  danger = false,
  children,
  onConfirm,
  onClose,
}: {
  title: string;
  actionLabel: string;
  danger?: boolean;
  children?: ReactNode;
  /** Runs after the code is accepted; throws ApiError to show its message. */
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [accepted, setAccepted] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (!accepted) {
        const digits = code.replace(/\s/g, "");
        if (digits.length !== 6) throw new ApiError("Enter the 6-digit code from your authenticator app.", 400);
        await apiFetch("auth/reauth", { method: "POST", body: { code: digits } });
        setAccepted(true);
      }
      await onConfirm();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
      setCode("");
      setBusy(false);
    }
  }

  return (
    <Modal title={title} icon={danger ? "warning" : "lock"} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-4" data-testid="confirm-code">
        {children}
        {!accepted && (
          <div>
            <label htmlFor="confirm-code-input" className={labelClass}>
              Confirm it&apos;s you: enter the code from your authenticator app
            </label>
            <input
              id="confirm-code-input"
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              placeholder="123456"
              className={`${inputClass} font-mono tracking-[0.3em]`}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/[^\d ]/g, "").slice(0, 7))}
            />
          </div>
        )}
        <FormError message={error} />
        <div className="flex justify-end gap-2">
          <button type="button" className={secondaryButtonClass} onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className={danger ? dangerButtonClass : primaryButtonClass} disabled={busy}>
            {busy ? "Please wait…" : actionLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}

type Pending = { title: string; actionLabel: string; danger?: boolean; action: () => Promise<void> };

/**
 * Runs a sensitive change; when the backend wants a fresh code first, asks
 * for it (ConfirmCode) and runs the change again. Other errors are thrown
 * to the caller. Render ``dialog``.
 */
export function useFreshAction() {
  const [pending, setPending] = useState<Pending | null>(null);

  async function run(change: Pending): Promise<boolean> {
    try {
      await change.action();
      return true;
    } catch (err) {
      if (!needsFreshCode(err)) throw err;
      setPending(change);
      return false;
    }
  }

  const dialog = pending ? (
    <ConfirmCode
      title={pending.title}
      actionLabel={pending.actionLabel}
      danger={pending.danger}
      onClose={() => setPending(null)}
      onConfirm={async () => {
        await pending.action();
        setPending(null);
      }}
    />
  ) : null;

  return { run, dialog };
}

/** A value shown once, with a copy button. */
export function CopyField({ label, value, testId, secret = false }: { label: string; value: string; testId: string; secret?: boolean }) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <span className={labelClass}>{label}</span>
      <div className="flex items-center gap-2">
        <code
          data-testid={testId}
          className={`min-w-0 flex-1 break-all rounded-xl px-3 py-2 font-mono text-xs ${
            secret ? "border border-amber-200 bg-amber-50 text-amber-900" : "bg-surface-container-low text-on-surface"
          }`}
        >
          {value}
        </code>
        <button
          type="button"
          className={secondaryButtonClass}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(value);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 2000);
            } catch {
              setCopied(false);
            }
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}
