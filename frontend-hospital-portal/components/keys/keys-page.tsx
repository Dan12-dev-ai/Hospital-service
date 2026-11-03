"use client";

import { useState } from "react";
import Link from "next/link";
import { cn } from "cn";
import { ChevronDown, ChevronRight, Plus, TriangleAlert } from "lucide-react";
import {
  EmptyState,
  ErrorState,
  FormError,
  LoadingState,
  Modal,
  dangerButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { PageHeader } from "@/components/shell/dashboard-shell";
import { useToast } from "@/components/shell/toast";
import { CopyField, useFreshAction } from "@/components/keys/confirm-code";
import { KeySettings } from "@/components/keys/key-settings";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import {
  ABILITIES,
  NOTIFY_SCOPE,
  SWAGGER_URL,
  timeAgo,
  type Connection,
  type ConnectionList,
  type ConnectionMode,
  type NewConnectionResult,
} from "@/lib/connect-types";

export function ModeBadge({ mode }: { mode: ConnectionMode }) {
  return (
    <span
      data-testid="mode-badge"
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
        mode === "live" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-800"
      )}
    >
      {mode === "live" ? "Live" : "Test"}
    </span>
  );
}

/**
 * API keys: the hospital's systems connected to the integration API (Test or
 * Live), what each may do (scopes), and per key: its client ID, the address
 * allow-list, public-key authentication, rotating the secret, revoking it.
 * Every change asks for a fresh authenticator code.
 */
export function KeysPage() {
  const { data, error, loading, reload } = useApi<ConnectionList>("connections");
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<Connection | null>(null);
  const toast = useToast();

  return (
    <div>
      <PageHeader
        title="API keys"
        description="Each key lets one of your systems call the Endod API. Test keys check everything and save nothing; Live keys work with real patients."
        actions={
          <button type="button" className={primaryButtonClass} onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" />
            Create API key
          </button>
        }
      />

      {loading && !data && <LoadingState label="Loading your keys…" />}
      {error && <ErrorState message={error.message} onRetry={reload} />}
      {data && data.items.length === 0 && (
        <div className="rounded-lg border border-dashed border-neutral-300">
          <EmptyState icon="key" title="No API keys yet">
            Create a <strong>Test</strong> key to start building: it checks every request and saves nothing.
          </EmptyState>
        </div>
      )}
      {data && data.items.length > 0 && (
        <ul className="divide-y divide-neutral-200 rounded-lg border border-neutral-200">
          {data.items.map((connection) => (
            <KeyRow
              key={connection.id}
              connection={connection}
              onRevoke={() => setRevoking(connection)}
              onChanged={reload}
            />
          ))}
        </ul>
      )}
      {data && (
        <dl className="mt-8 grid gap-4 text-xs sm:grid-cols-2">
          <div>
            <dt className="text-neutral-500">API base URL</dt>
            <dd className="mt-1 break-all font-mono text-neutral-900" data-testid="api-url">{data.api_url}</dd>
          </div>
          <div>
            <dt className="text-neutral-500">Token URL</dt>
            <dd className="mt-1 break-all font-mono text-neutral-900">{data.token_url}</dd>
          </div>
          <div>
            <dt className="text-neutral-500">Patient numbers (MRN) system</dt>
            <dd className="mt-1 break-all font-mono text-neutral-900">{data.mrn_system}</dd>
          </div>
          <div>
            <dt className="text-neutral-500">API reference</dt>
            <dd className="mt-1">
              <a href={SWAGGER_URL} target="_blank" rel="noreferrer" className="font-medium text-neutral-900 underline underline-offset-2">
                Swagger
              </a>
            </dd>
          </div>
        </dl>
      )}

      {creating && (
        <CreateKey
          onClose={() => {
            setCreating(false);
            reload();
          }}
        />
      )}
      {revoking && (
        <Revoke
          connection={revoking}
          onClose={() => setRevoking(null)}
          onDone={() => {
            toast(`${revoking.name} revoked`);
            setRevoking(null);
            reload();
          }}
        />
      )}
    </div>
  );
}

function KeyRow({ connection, onRevoke, onChanged }: { connection: Connection; onRevoke: () => void; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <li data-testid="connection" className="px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex min-w-0 items-center gap-2 text-left"
        >
          {open ? <ChevronDown className="h-4 w-4 text-neutral-400" /> : <ChevronRight className="h-4 w-4 text-neutral-400" />}
          <span className="truncate text-sm font-medium text-neutral-900">{connection.name}</span>
          <ModeBadge mode={connection.mode} />
        </button>
        <div className="flex items-center gap-4">
          <code className="hidden font-mono text-xs text-neutral-500 sm:inline">{connection.client_id}</code>
          <span className="text-xs text-neutral-500" data-testid="last-used">
            {connection.last_used_at ? `Used ${timeAgo(connection.last_used_at)}` : "Not used yet"}
          </span>
          <button type="button" onClick={onRevoke} className="text-xs font-medium text-rose-600 hover:underline">
            Revoke
          </button>
        </div>
      </div>
      <ul className="mt-2 flex flex-wrap gap-1.5 pl-6" aria-label="Scopes">
        {connection.scopes.map((scope) => (
          <li key={scope} className="rounded border border-neutral-200 bg-neutral-50 px-1.5 py-0.5 font-mono text-[11px] text-neutral-600">
            {scope}
          </li>
        ))}
      </ul>
      {open && (
        <div className="pl-6">
          <KeySettings connection={connection} onChanged={onChanged} />
        </div>
      )}
    </li>
  );
}

function Revoke({ connection, onClose, onDone }: { connection: Connection; onClose: () => void; onDone: () => void }) {
  const fresh = useFreshAction();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function revoke() {
    setBusy(true);
    setError(null);
    try {
      const done = await fresh.run({
        title: `Revoke ${connection.name}`,
        actionLabel: "Revoke",
        danger: true,
        action: async () => {
          await apiFetch(`connections/${connection.id}/disconnect`, { method: "POST" });
          onDone();
        },
      });
      if (!done) setBusy(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not revoke the key.");
      setBusy(false);
    }
  }

  if (fresh.dialog) return fresh.dialog;
  return (
    <Modal title={`Revoke ${connection.name}?`} icon="warning" onClose={onClose}>
      <p className="text-sm text-neutral-600">
        The system using it stops working immediately. Records it already sent stay in Endod.
      </p>
      <FormError message={error} />
      <div className="flex justify-end gap-2">
        <button type="button" className={secondaryButtonClass} onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button type="button" className={dangerButtonClass} onClick={revoke} disabled={busy}>
          Revoke key
        </button>
      </div>
    </Modal>
  );
}

function CreateKey({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [mode, setMode] = useState<ConnectionMode>("test");
  const [notifyUrl, setNotifyUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<NewConnectionResult | null>(null);
  const fresh = useFreshAction();
  const notify = chosen.includes(NOTIFY_SCOPE);

  function toggle(scope: string) {
    setChosen((current) => (current.includes(scope) ? current.filter((s) => s !== scope) : [...current, scope]));
  }

  async function create() {
    setError(null);
    if (name.trim().length < 2) return setError("Give the key a name, e.g. “Main lab system”.");
    if (chosen.length === 0) return setError("Choose at least one scope.");
    if (notify && !/^https:\/\/\S+$/i.test(notifyUrl.trim())) {
      return setError("Give the https:// address where your system receives webhooks.");
    }
    setBusy(true);
    try {
      await fresh.run({
        title: "Create this API key",
        actionLabel: "Create key",
        action: async () => {
          const created = await apiFetch<NewConnectionResult>("connections", {
            method: "POST",
            body: { name: name.trim(), scopes: chosen, mode, webhook_url: notify ? notifyUrl.trim() : null },
          });
          setResult(created);
        },
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the key.");
    } finally {
      setBusy(false);
    }
  }

  if (fresh.dialog && !result) return fresh.dialog;

  if (result) {
    return (
      <Modal title="Your API key" icon="key" onClose={onClose}>
        <div className="flex flex-col gap-4" data-testid="connect-done">
          <div role="alert" className="flex gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            <TriangleAlert className="h-4 w-4 shrink-0" />
            <span>
              <strong>Save the secret now.</strong> It is shown only this once: Endod keeps no readable copy. If it
              is lost, rotate it.
            </span>
          </div>
          <CopyField label="Client ID" value={result.connection.client_id} testId="client-id" />
          <CopyField label="Client secret" value={result.client_secret} testId="client-secret" secret />
          {result.webhook_secret && (
            <CopyField label="Webhook signing secret" value={result.webhook_secret} testId="notify-secret" secret />
          )}
          <Link
            href={`/keys/${result.connection.id}/setup-guide`}
            target="_blank"
            rel="noreferrer"
            className={cn(secondaryButtonClass, "self-start")}
          >
            Download setup guide
          </Link>
          <div className="flex justify-end">
            <button type="button" className={primaryButtonClass} onClick={onClose}>
              I saved the secret
            </button>
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="Create API key" icon="key" onClose={onClose}>
      <div className="flex flex-col gap-5">
        <div>
          <label htmlFor="connection-name" className={labelClass}>
            Name
          </label>
          <input
            id="connection-name"
            className={inputClass}
            value={name}
            maxLength={80}
            placeholder="e.g. Main lab system"
            autoFocus
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <fieldset>
          <legend className={labelClass}>Mode</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {(
              [
                ["test", "Test", "Checks everything, saves nothing"],
                ["live", "Live", "Real patients and records"],
              ] as const
            ).map(([value, label, hint]) => (
              <label
                key={value}
                className={cn(
                  "flex cursor-pointer items-start gap-2 rounded-md border p-3 text-sm",
                  mode === value ? "border-neutral-900" : "border-neutral-200"
                )}
              >
                <input type="radio" name="mode" className="mt-1" checked={mode === value} onChange={() => setMode(value)} />
                <span>
                  <span className="block font-medium text-neutral-900">{label}</span>
                  <span className="block text-xs text-neutral-500">{hint}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend className={labelClass}>Scopes</legend>
          <div className="grid max-h-72 gap-1 overflow-y-auto rounded-md border border-neutral-200 p-2 sm:grid-cols-2">
            {ABILITIES.map((ability) => (
              <label key={ability.scope} className="flex cursor-pointer items-start gap-2 rounded px-2 py-1.5 text-sm hover:bg-neutral-50">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={chosen.includes(ability.scope)}
                  onChange={() => toggle(ability.scope)}
                />
                <span>
                  <span className="block font-medium text-neutral-900">{ability.label}</span>
                  <span className="block font-mono text-[11px] text-neutral-500">{ability.scope}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        {notify && (
          <div>
            <label htmlFor="notify-url" className={labelClass}>
              Webhook URL
            </label>
            <input
              id="notify-url"
              className={inputClass}
              value={notifyUrl}
              placeholder="https://your-system.example.com/endod"
              onChange={(e) => setNotifyUrl(e.target.value)}
            />
          </div>
        )}
        <FormError message={error} />
        <div className="flex justify-end gap-2">
          <button type="button" className={secondaryButtonClass} onClick={onClose}>
            Cancel
          </button>
          <button type="button" className={primaryButtonClass} onClick={create} disabled={busy}>
            Create key
          </button>
        </div>
      </div>
    </Modal>
  );
}
