"use client";

import { useState } from "react";
import { cn } from "cn";
import { RefreshCw, RotateCw, Send } from "lucide-react";
import { ErrorState, FormError, LoadingState, inputClass, labelClass, secondaryButtonClass } from "@/components/common/states";
import { PageHeader, Panel } from "@/components/shell/dashboard-shell";
import { useToast } from "@/components/shell/toast";
import { WithKey } from "@/components/keys/key-picker";
import { useKeyChanges } from "@/components/keys/key-settings";
import { useSignedIn } from "@/components/session/session-context";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import type { Connection, Delivery } from "@/lib/connect-types";
import { formatDateTime } from "@/lib/format";

/** Webhooks: where a key's events go, their signing secret, a test event, and recent deliveries. */
export function WebhooksPage() {
  return (
    <div>
      <PageHeader
        title="Webhooks"
        description="Endod POSTs events to your system (bookings, patient links, dispensing), signed with Endod-Signature. Test keys receive only the test event."
      />
      <WithKey>{(connection, reload) => <KeyWebhook connection={connection} onChanged={reload} />}</WithKey>
    </div>
  );
}

function KeyWebhook({ connection, onChanged }: { connection: Connection; onChanged: () => void }) {
  const toast = useToast();
  const changes = useKeyChanges(onChanged);
  const [url, setUrl] = useState(connection.webhook_url ?? "");
  const [deliveriesVersion, setDeliveriesVersion] = useState(0);
  const base = `connections/${connection.id}`;

  async function sendTest() {
    changes.setError(null);
    try {
      await apiFetch(`${base}/webhook/test`, { method: "POST" });
      toast("Test event queued");
      setDeliveriesVersion((v) => v + 1);
    } catch (err) {
      changes.setError(err instanceof ApiError ? err.message : "Could not send the test event.");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Panel title="Endpoint" description="https only, reachable on the internet. Events are retried for 24 hours.">
        <label htmlFor="webhook-url" className={labelClass}>
          Webhook URL
        </label>
        <input
          id="webhook-url"
          aria-label="Webhook URL"
          className={inputClass}
          value={url}
          placeholder="https://your-system.example.com/endod"
          onChange={(e) => setUrl(e.target.value)}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            className={secondaryButtonClass}
            disabled={!url.trim()}
            onClick={() =>
              changes.ask({
                title: "Save the webhook",
                actionLabel: "Save",
                path: `${base}/webhook`,
                body: { url: url.trim() },
                done: (answer) => {
                  if (answer.webhook_secret) {
                    changes.reveal({ title: "Webhook signing secret", label: "Webhook secret", value: String(answer.webhook_secret) });
                  } else {
                    toast("Webhook saved");
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
                <Send className="h-3.5 w-3.5" />
                Send test event
              </button>
              <button
                type="button"
                className={secondaryButtonClass}
                onClick={() =>
                  changes.ask({
                    title: "Rotate the webhook secret",
                    actionLabel: "Rotate",
                    danger: true,
                    path: `${base}/webhook/rotate-secret`,
                    body: {},
                    done: (answer) =>
                      changes.reveal({ title: "New webhook secret", label: "Webhook secret", value: String(answer.webhook_secret) }),
                  })
                }
              >
                <RotateCw className="h-3.5 w-3.5" />
                Rotate signing secret
              </button>
              <button
                type="button"
                className={cn(secondaryButtonClass, "text-rose-600")}
                onClick={() =>
                  changes.ask({
                    title: "Remove the webhook",
                    actionLabel: "Remove",
                    danger: true,
                    path: `${base}/webhook`,
                    body: { url: null },
                    done: () => {
                      setUrl("");
                      toast("Webhook removed");
                    },
                  })
                }
              >
                Remove
              </button>
            </>
          )}
        </div>
        <div className="mt-3">
          <FormError message={changes.error} />
        </div>
      </Panel>
      <Deliveries base={base} version={deliveriesVersion} />
      {changes.dialogs}
    </div>
  );
}

function Deliveries({ base, version }: { base: string; version: number }) {
  const signedIn = useSignedIn();
  const { data, error, loading, reload } = useApi<{ items: Delivery[] }>(`${base}/deliveries?v=${version}`);
  const zone = signedIn?.hospital.timezone;
  return (
    <Panel
      title="Recent deliveries"
      description="The last 50 events sent to this key (kept 30 days)."
      actions={
        <button type="button" onClick={reload} className="inline-flex items-center gap-1 text-xs font-medium text-neutral-600 hover:text-neutral-900">
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      }
    >
      {loading && !data && <LoadingState label="Loading…" className="p-4 shadow-none" />}
      {error && <ErrorState message={error.message} onRetry={reload} className="p-4" />}
      {data && data.items.length === 0 && <p className="text-xs text-neutral-500">No events sent yet.</p>}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs" data-testid="delivery-log">
            <thead className="text-neutral-500">
              <tr>
                <th className="py-1.5 pr-3 font-medium">Time</th>
                <th className="py-1.5 pr-3 font-medium">Event</th>
                <th className="py-1.5 pr-3 font-medium">Status</th>
                <th className="py-1.5 pr-3 font-medium">Attempts</th>
                <th className="py-1.5 font-medium">Last answer</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.id} className="border-t border-neutral-100">
                  <td className="whitespace-nowrap py-1.5 pr-3">{formatDateTime(row.created_at, zone)}</td>
                  <td className="py-1.5 pr-3 font-mono">{row.event_type}</td>
                  <td
                    className={cn(
                      "py-1.5 pr-3 font-medium",
                      row.status === "delivered" ? "text-emerald-700" : row.status === "failed" ? "text-rose-600" : "text-amber-700"
                    )}
                  >
                    {row.status}
                  </td>
                  <td className="py-1.5 pr-3">{row.attempts}</td>
                  <td className="py-1.5">{row.last_status_code ?? row.last_error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
