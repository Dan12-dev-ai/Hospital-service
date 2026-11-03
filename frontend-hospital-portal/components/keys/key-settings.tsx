"use client";

import { useState, type ReactNode } from "react";
import { cn } from "cn";
import { RotateCw } from "lucide-react";
import {
  FormError,
  Modal,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { useToast } from "@/components/shell/toast";
import { CopyField, useFreshAction } from "@/components/keys/confirm-code";
import { ApiError, apiFetch } from "@/lib/api";
import type { Connection } from "@/lib/connect-types";

/** A change to a key that needs a fresh authenticator code: what to send, and what to do with the answer. */
export type KeyChange = {
  title: string;
  actionLabel: string;
  danger?: boolean;
  path: string;
  body: Record<string, unknown>;
  done?: (answer: Record<string, unknown>) => void;
};

/**
 * Sends changes to a key (asking for a fresh authenticator code when the
 * backend wants one), and shows a new secret once. Render ``dialogs``.
 */
export function useKeyChanges(onChanged: () => void) {
  const fresh = useFreshAction();
  const [error, setError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<{ title: string; label: string; value: string } | null>(null);

  async function ask(change: KeyChange) {
    setError(null);
    try {
      await fresh.run({
        title: change.title,
        actionLabel: change.actionLabel,
        danger: change.danger,
        action: async () => {
          const answer = await apiFetch<Record<string, unknown>>(change.path, { method: "POST", body: change.body });
          change.done?.(answer);
          onChanged();
        },
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the change.");
    }
  }

  const dialogs = (
    <>
      {fresh.dialog}
      {revealed && (
        <Modal title={revealed.title} icon="key" onClose={() => setRevealed(null)}>
          <div role="alert" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            <strong>Save it now.</strong> It is shown only this once. The old one has stopped working.
          </div>
          <CopyField label={revealed.label} value={revealed.value} testId="revealed-secret" secret />
          <div className="flex justify-end">
            <button type="button" className={primaryButtonClass} onClick={() => setRevealed(null)}>
              I saved it
            </button>
          </div>
        </Modal>
      )}
    </>
  );

  return { ask, error, setError, reveal: setRevealed, dialogs };
}

/**
 * One key's settings: its client ID, where it may call from, how it
 * authenticates (rotate the secret, or use a public key instead).
 */
export function KeySettings({ connection, onChanged }: { connection: Connection; onChanged: () => void }) {
  const toast = useToast();
  const changes = useKeyChanges(onChanged);
  const [ips, setIps] = useState(connection.allowed_ips.join("\n"));
  const [jwks, setJwks] = useState("");
  const base = `connections/${connection.id}`;

  return (
    <div data-testid="advanced" className="mt-4 flex flex-col gap-6 border-t border-neutral-100 pt-4 text-sm">
      <Row title="Client ID">
        <code className="break-all rounded bg-neutral-100 px-2 py-1 font-mono text-xs">{connection.client_id}</code>
        <a href={`/keys/${connection.id}/setup-guide`} target="_blank" rel="noreferrer" className="ml-3 text-xs font-medium text-neutral-900 underline underline-offset-2">
          Setup guide
        </a>
      </Row>

      <Row title="Allowed IP addresses" hint="Only these addresses or ranges may use this key (one per line). Empty: any address.">
        <textarea
          aria-label="Allowed IP addresses"
          className={cn(inputClass, "min-h-[72px] font-mono text-xs")}
          value={ips}
          placeholder={"196.188.10.0/24\n41.79.1.5"}
          onChange={(e) => setIps(e.target.value)}
        />
        <button
          type="button"
          className={cn(secondaryButtonClass, "mt-2")}
          onClick={() =>
            changes.ask({
              title: "Save the allowed addresses",
              actionLabel: "Save",
              path: `${base}/ip-restriction`,
              body: { allowed_ips: ips.split(/[\s,]+/).filter(Boolean) },
              done: () => toast("Allowed addresses saved"),
            })
          }
        >
          Save addresses
        </button>
      </Row>

      <Row
        title="Authentication"
        hint={
          connection.auth_method === "private_key_jwt"
            ? `Public key (private_key_jwt): ${connection.public_keys} key${connection.public_keys === 1 ? "" : "s"}. The client secret does not work.`
            : "Client secret (OAuth 2.0 client credentials)."
        }
      >
        <button
          type="button"
          className={secondaryButtonClass}
          onClick={() =>
            changes.ask({
              title: "Rotate the client secret",
              actionLabel: "Rotate secret",
              danger: true,
              path: `${base}/rotate-secret`,
              body: {},
              done: (answer) =>
                changes.reveal({ title: "New client secret", label: "Client secret", value: String(answer.client_secret) }),
            })
          }
        >
          <RotateCw className="h-3.5 w-3.5" />
          {connection.auth_method === "private_key_jwt" ? "Go back to a client secret" : "Rotate secret"}
        </button>
        <label htmlFor={`jwks-${connection.id}`} className={cn(labelClass, "mt-4")}>
          Use a public key instead (paste your JWKS: ES256 or RS256, public keys only)
        </label>
        <textarea
          id={`jwks-${connection.id}`}
          className={cn(inputClass, "min-h-[72px] font-mono text-xs")}
          value={jwks}
          placeholder='{"keys": [{"kty": "EC", "crv": "P-256", "kid": "my-key-1", "x": "...", "y": "..."}]}'
          onChange={(e) => setJwks(e.target.value)}
        />
        <button
          type="button"
          className={cn(secondaryButtonClass, "mt-2")}
          disabled={!jwks.trim()}
          onClick={() =>
            changes.ask({
              title: "Switch to public-key authentication",
              actionLabel: "Use this key",
              danger: true,
              path: `${base}/public-key`,
              body: { jwks: jwks.trim() },
              done: () => {
                setJwks("");
                toast("Public key saved: the client secret no longer works");
              },
            })
          }
        >
          Save public key
        </button>
      </Row>

      <FormError message={changes.error} />
      {changes.dialogs}
    </div>
  );
}

export function Row({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="text-xs font-medium text-neutral-900">{title}</h3>
      {hint && <p className="mb-2 mt-0.5 text-xs text-neutral-500">{hint}</p>}
      <div className={hint ? "" : "mt-2"}>{children}</div>
    </section>
  );
}
