"use client";

import { useState, type ReactNode } from "react";
import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import {
  ErrorState,
  FormError,
  LoadingState,
  Modal,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { useSignedIn } from "@/components/session/session-context";
import { ConfirmPassword, CopyField } from "@/components/connect/confirm-password";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import type { Connection, Delivery, RequestLogEntry } from "@/lib/connect-types";
import { formatDateTime } from "@/lib/format";

/** A change that needs the password again: what to send, and what to say afterwards. */
type PendingChange = {
  title: string;
  actionLabel: string;
  danger?: boolean;
  path: string;
  body: Record<string, unknown>;
  done: (answer: Record<string, unknown>) => void;
};

/**
 * The technical settings of one connection, for the hospital's IT staff:
 * IP restriction, public-key authentication, secret rotation, the webhook,
 * and the request and delivery logs.
 */
export function AdvancedPanel({ connection, onChanged }: { connection: Connection; onChanged: () => void }) {
  const { showToast } = useDashboard();
  const [pending, setPending] = useState<PendingChange | null>(null);
  const [revealed, setRevealed] = useState<{ title: string; label: string; value: string } | null>(null);
  const [ips, setIps] = useState(connection.allowed_ips.join("\n"));
  const [jwks, setJwks] = useState("");
  const [webhookUrl, setWebhookUrl] = useState(connection.webhook_url ?? "");
  const [error, setError] = useState<string | null>(null);
  const base = `connections/${connection.id}`;

  function ask(change: Omit<PendingChange, "done"> & { done?: PendingChange["done"] }) {
    setError(null);
    setPending({ done: () => undefined, ...change });
  }

  async function sendTest() {
    setError(null);
    try {
      await apiFetch(`${base}/webhook/test`, { method: "POST" });
      showToast("Test event queued: see the deliveries below");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send the test event.");
    }
  }

  return (
    <div data-testid="advanced" className="mt-4 flex flex-col gap-5 border-t border-slate-100 pt-4 text-sm">
      <Section title="Client ID">
        <code className="break-all rounded-lg bg-surface-container-low px-2 py-1 font-mono text-xs">{connection.client_id}</code>
      </Section>

      <Section title="IP restriction" hint="Only these addresses or ranges may use this connection (one per line). Empty: any address.">
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
            ask({
              title: "Save the IP restriction",
              actionLabel: "Save",
              path: `${base}/ip-restriction`,
              body: { allowed_ips: ips.split(/[\s,]+/).filter(Boolean) },
              done: () => showToast("IP restriction saved"),
            })
          }
        >
          Save addresses
        </button>
      </Section>

      <Section
        title="Authentication"
        hint={
          connection.auth_method === "private_key_jwt"
            ? `Public key (private_key_jwt): ${connection.public_keys} key${connection.public_keys === 1 ? "" : "s"}. The client secret does not work.`
            : "Client secret (OAuth 2.0 client credentials)."
        }
      >
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className={secondaryButtonClass}
            onClick={() =>
              ask({
                title: "Rotate the client secret",
                actionLabel: "Rotate secret",
                danger: true,
                path: `${base}/rotate-secret`,
                body: {},
                done: (answer) =>
                  setRevealed({ title: "New client secret", label: "Client secret", value: String(answer.client_secret) }),
              })
            }
          >
            <Icon name="autorenew" className="text-[16px]" />
            {connection.auth_method === "private_key_jwt" ? "Go back to a client secret" : "Rotate secret"}
          </button>
        </div>
        <label htmlFor={`jwks-${connection.id}`} className={cn(labelClass, "mt-3")}>
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
            ask({
              title: "Switch to public-key authentication",
              actionLabel: "Use this key",
              danger: true,
              path: `${base}/public-key`,
              body: { jwks: jwks.trim() },
              done: () => {
                setJwks("");
                showToast("Public key saved: the client secret no longer works");
              },
            })
          }
        >
          Save public key
        </button>
      </Section>

      <Section title="Webhook" hint="Booking and patient-link events are POSTed here, signed with the webhook secret (https only).">
        <input
          aria-label="Webhook URL"
          className={inputClass}
          value={webhookUrl}
          placeholder="https://your-system.example.com/endod"
          onChange={(e) => setWebhookUrl(e.target.value)}
        />
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            type="button"
            className={secondaryButtonClass}
            disabled={!webhookUrl.trim()}
            onClick={() =>
              ask({
                title: "Save the webhook",
                actionLabel: "Save",
                path: `${base}/webhook`,
                body: { url: webhookUrl.trim() },
                done: (answer) => {
                  if (answer.webhook_secret) {
                    setRevealed({ title: "Webhook secret", label: "Webhook secret", value: String(answer.webhook_secret) });
                  } else {
                    showToast("Webhook saved");
                  }
                },
              })
            }
          >
            Save webhook
          </button>
          {connection.webhook_url && (
            <>
              <button type="button" className={secondaryButtonClass} onClick={sendTest}>
                <Icon name="send" className="text-[16px]" />
                Send test event
              </button>
              <button
                type="button"
                className={secondaryButtonClass}
                onClick={() =>
                  ask({
                    title: "Rotate the webhook secret",
                    actionLabel: "Rotate",
                    danger: true,
                    path: `${base}/webhook/rotate-secret`,
                    body: {},
                    done: (answer) =>
                      setRevealed({ title: "New webhook secret", label: "Webhook secret", value: String(answer.webhook_secret) }),
                  })
                }
              >
                Rotate webhook secret
              </button>
              <button
                type="button"
                className={secondaryButtonClass}
                onClick={() =>
                  ask({
                    title: "Remove the webhook",
                    actionLabel: "Remove",
                    danger: true,
                    path: `${base}/webhook`,
                    body: { url: null },
                    done: () => {
                      setWebhookUrl("");
                      showToast("Webhook removed");
                    },
                  })
                }
              >
                Remove
              </button>
            </>
          )}
        </div>
      </Section>

      <FormError message={error} />
      <RequestLog base={base} />
      <Deliveries base={base} />

      {pending && (
        <ConfirmPassword
          title={pending.title}
          actionLabel={pending.actionLabel}
          danger={pending.danger}
          onClose={() => setPending(null)}
          onConfirm={async (password) => {
            const answer = await apiFetch<Record<string, unknown>>(pending.path, {
              method: "POST",
              body: { ...pending.body, password },
            });
            setPending(null);
            pending.done(answer);
            onChanged();
          }}
        />
      )}
      {revealed && (
        <Modal title={revealed.title} icon="key" onClose={() => setRevealed(null)}>
          <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
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
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">{title}</h3>
      {hint && <p className="mb-2 mt-0.5 text-xs text-slate-500">{hint}</p>}
      <div className={hint ? "" : "mt-2"}>{children}</div>
    </section>
  );
}

function RequestLog({ base }: { base: string }) {
  const signedIn = useSignedIn();
  const { data, error, loading, reload } = useApi<{ items: RequestLogEntry[] }>(`${base}/requests`);
  const zone = signedIn?.hospital.timezone;
  return (
    <Section title="Recent requests" hint="The last 50 calls (kept 30 days). Never the data sent.">
      {loading && !data && <LoadingState label="Loading…" className="p-4" />}
      {error && <ErrorState message={error.message} onRetry={reload} className="p-4" />}
      {data && data.items.length === 0 && <p className="text-xs text-slate-500">No requests yet.</p>}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs" data-testid="request-log">
            <thead className="text-slate-400">
              <tr>
                <th className="py-1 pr-3 font-semibold">Time</th>
                <th className="py-1 pr-3 font-semibold">Request</th>
                <th className="py-1 pr-3 font-semibold">Status</th>
                <th className="py-1 pr-3 font-semibold">Duration</th>
                <th className="py-1 font-semibold">IP</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row, index) => (
                <tr key={`${row.at}-${index}`} className="border-t border-slate-100">
                  <td className="py-1 pr-3 whitespace-nowrap">{formatDateTime(row.at, zone)}</td>
                  <td className="py-1 pr-3 font-mono">
                    {row.method} {row.path}
                  </td>
                  <td className={cn("py-1 pr-3 font-semibold", row.status < 400 ? "text-emerald-700" : "text-rose-600")}>
                    {row.status}
                  </td>
                  <td className="py-1 pr-3">{row.duration_ms} ms</td>
                  <td className="py-1 font-mono">{row.ip ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

function Deliveries({ base }: { base: string }) {
  const signedIn = useSignedIn();
  const { data, error, loading, reload } = useApi<{ items: Delivery[] }>(`${base}/deliveries`);
  const zone = signedIn?.hospital.timezone;
  return (
    <Section title="Webhook deliveries" hint="The last 50 events sent (kept 30 days).">
      <button type="button" onClick={reload} className="mb-2 text-xs font-semibold text-pine-green hover:underline">
        Refresh
      </button>
      {loading && !data && <LoadingState label="Loading…" className="p-4" />}
      {error && <ErrorState message={error.message} onRetry={reload} className="p-4" />}
      {data && data.items.length === 0 && <p className="text-xs text-slate-500">No events sent yet.</p>}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs" data-testid="delivery-log">
            <thead className="text-slate-400">
              <tr>
                <th className="py-1 pr-3 font-semibold">Time</th>
                <th className="py-1 pr-3 font-semibold">Event</th>
                <th className="py-1 pr-3 font-semibold">Status</th>
                <th className="py-1 pr-3 font-semibold">Attempts</th>
                <th className="py-1 font-semibold">Last answer</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.id} className="border-t border-slate-100">
                  <td className="py-1 pr-3 whitespace-nowrap">{formatDateTime(row.created_at, zone)}</td>
                  <td className="py-1 pr-3 font-mono">{row.event_type}</td>
                  <td
                    className={cn(
                      "py-1 pr-3 font-semibold",
                      row.status === "delivered" ? "text-emerald-700" : row.status === "failed" ? "text-rose-600" : "text-amber-700"
                    )}
                  >
                    {row.status}
                  </td>
                  <td className="py-1 pr-3">{row.attempts}</td>
                  <td className="py-1">{row.last_status_code ?? row.last_error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
