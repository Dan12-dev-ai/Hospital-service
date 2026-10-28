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
import { ApiError } from "@/lib/api";

/**
 * Asks the signed-in admin for their password again before a sensitive
 * change (connecting a system, its credentials, disconnecting it). The
 * backend checks it, counts wrong ones toward the lockout, and audits it.
 */
export function ConfirmPassword({
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
  /** Does the change with the password; throws ApiError to show its message. */
  onConfirm: (password: string) => Promise<void>;
  onClose: () => void;
}) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!password) return setError("Enter your password.");
    setBusy(true);
    setError(null);
    try {
      await onConfirm(password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
      setBusy(false);
    }
  }

  return (
    <Modal title={title} icon={danger ? "warning" : "lock"} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-4" data-testid="confirm-password">
        {children}
        <div>
          <label htmlFor="confirm-password-input" className={labelClass}>
            Confirm it&apos;s you: enter your password
          </label>
          <input
            id="confirm-password-input"
            type="password"
            autoComplete="current-password"
            autoFocus
            className={inputClass}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
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
