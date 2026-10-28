"use client";

import { useState } from "react";
import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import {
  EmptyState,
  ErrorState,
  dangerButtonClass,
  FormError,
  LoadingState,
  Modal,
  RoleGate,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { useSignedIn } from "@/components/session/session-context";
import { CopyField, useFreshAction } from "@/components/connect/confirm-code";
import { AdvancedPanel } from "@/components/connect/advanced-panel";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import {
  ABILITIES,
  NOTIFY_SCOPE,
  timeAgo,
  type Connection,
  type ConnectionList,
  type ConnectionMode,
  type NewConnectionResult,
} from "@/lib/connect-types";

export function ConnectPage() {
  return (
    <RoleGate roles={["admin"]} what="connecting your hospital's systems">
      <ApprovedOnly />
    </RoleGate>
  );
}

function ApprovedOnly() {
  const signedIn = useSignedIn();
  if (!signedIn) return null;
  if (signedIn.hospital.status !== "approved") {
    return (
      <div
        data-testid="connect-not-approved"
        className="flex flex-col items-center gap-2 rounded-3xl border border-card-border/80 bg-white p-14 text-center shadow-soft"
      >
        <Icon name="lock" className="text-[28px] text-slate-500" />
        <h1 className="text-lg font-bold text-slate-900">Not available yet</h1>
        <p className="max-w-md text-xs text-slate-500">
          Only hospitals approved by Endod can connect their own systems.
        </p>
      </div>
    );
  }
  return <Connections />;
}

export function ModeBadge({ mode }: { mode: ConnectionMode }) {
  return (
    <span
      data-testid="mode-badge"
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        mode === "live" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"
      )}
    >
      {mode === "live" ? "Live" : "Test"}
    </span>
  );
}

function Connections() {
  const { data, error, loading, reload } = useApi<ConnectionList>("connections");
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState<Connection | null>(null);
  const { showToast } = useDashboard();

  return (
    <div className="flex w-full flex-col gap-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Connect your system</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Let your hospital&apos;s own system send records to Endod and see bookings, without typing anything twice.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {data && (
            <a
              href={data.docs_url}
              target="_blank"
              rel="noreferrer"
              className="text-xs font-semibold text-pine-green underline-offset-2 hover:underline"
            >
              Developer guide
            </a>
          )}
          <button type="button" className={cn(primaryButtonClass, "px-5 py-2.5 text-sm")} onClick={() => setConnecting(true)}>
            <Icon name="add_link" className="text-[18px]" />
            Connect a system
          </button>
        </div>
      </header>

      {loading && !data && <LoadingState label="Loading your connections…" />}
      {error && <ErrorState message={error.message} onRetry={reload} />}
      {data && data.items.length === 0 && (
        <div className="rounded-3xl border border-card-border/80 bg-white shadow-soft">
          <EmptyState icon="hub" title="No systems connected yet">
            Click &ldquo;Connect a system&rdquo; to let your lab, pharmacy or records system send results to Endod.
          </EmptyState>
        </div>
      )}
      {data && data.items.length > 0 && (
        <ul className="flex flex-col gap-3">
          {data.items.map((connection) => (
            <ConnectionCard
              key={connection.id}
              connection={connection}
              onDisconnect={() => setDisconnecting(connection)}
              onChanged={reload}
            />
          ))}
        </ul>
      )}

      {connecting && (
        <ConnectFlow
          onClose={() => {
            setConnecting(false);
            reload();
          }}
        />
      )}
      {disconnecting && (
        <Disconnect
          connection={disconnecting}
          onClose={() => setDisconnecting(null)}
          onDone={() => {
            showToast(`${disconnecting.name} disconnected`);
            setDisconnecting(null);
            reload();
          }}
        />
      )}
    </div>
  );
}

function Disconnect({ connection, onClose, onDone }: { connection: Connection; onClose: () => void; onDone: () => void }) {
  const fresh = useFreshAction();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function disconnect() {
    setBusy(true);
    setError(null);
    try {
      const done = await fresh.run({
        title: `Disconnect ${connection.name}`,
        actionLabel: "Disconnect",
        danger: true,
        action: async () => {
          await apiFetch(`connections/${connection.id}/disconnect`, { method: "POST" });
          onDone();
        },
      });
      if (!done) setBusy(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not disconnect.");
      setBusy(false);
    }
  }

  if (fresh.dialog) return fresh.dialog;
  return (
    <Modal title={`Disconnect ${connection.name}?`} icon="warning" onClose={onClose}>
      <p className="text-sm text-slate-600">It stops working immediately. Records it already sent stay in Endod.</p>
      <FormError message={error} />
      <div className="flex justify-end gap-2">
        <button type="button" className={secondaryButtonClass} onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button type="button" className={dangerButtonClass} onClick={disconnect} disabled={busy}>
          Disconnect
        </button>
      </div>
    </Modal>
  );
}

function ConnectionCard({
  connection,
  onDisconnect,
  onChanged,
}: {
  connection: Connection;
  onDisconnect: () => void;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li data-testid="connection" className="rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-base font-bold text-slate-900">{connection.name}</h2>
            <ModeBadge mode={connection.mode} />
          </div>
          <p className="mt-1 text-xs text-slate-500" data-testid="last-used">
            {connection.last_used_at ? `Last used ${timeAgo(connection.last_used_at)}` : "Not used yet"}
          </p>
        </div>
        <button
          type="button"
          onClick={onDisconnect}
          className="inline-flex items-center gap-1.5 rounded-xl border border-rose-200 px-3 py-1.5 text-xs font-semibold text-rose-600 hover:bg-rose-50"
        >
          <Icon name="link_off" className="text-[16px]" />
          Disconnect
        </button>
      </div>
      <ul className="mt-3 flex flex-wrap gap-2" aria-label="What it can do">
        {connection.abilities.map((ability) => (
          <li key={ability} className="flex items-center gap-1 rounded-full bg-pine-light px-2.5 py-1 text-[11px] font-medium text-pine-green">
            <Icon name="check" className="text-[14px]" />
            {ability}
          </li>
        ))}
      </ul>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-slate-800"
      >
        <Icon name={open ? "expand_less" : "expand_more"} className="text-[18px]" />
        Advanced
      </button>
      {open && <AdvancedPanel connection={connection} onChanged={onChanged} />}
    </li>
  );
}

// --- the three steps -------------------------------------------------------------------------------

type Step = 1 | 2 | 3;

function ConnectFlow({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<Step>(1);
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [mode, setMode] = useState<ConnectionMode>("live");
  const [notifyUrl, setNotifyUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<NewConnectionResult | null>(null);
  const fresh = useFreshAction();
  const notify = chosen.includes(NOTIFY_SCOPE);

  function toggle(scope: string) {
    setChosen((current) => (current.includes(scope) ? current.filter((s) => s !== scope) : [...current, scope]));
  }

  function next() {
    setError(null);
    if (step === 1) {
      if (name.trim().length < 2) return setError("Give the system a name, e.g. “Main lab system”.");
      return setStep(2);
    }
    if (chosen.length === 0) return setError("Choose at least one thing it can do.");
    if (notify && !/^https:\/\/\S+$/i.test(notifyUrl.trim())) {
      return setError("Give the https:// address where your system wants to be notified.");
    }
    void create();
  }

  async function create() {
    setBusy(true);
    try {
      await fresh.run({
        title: "Connect this system",
        actionLabel: "Connect",
        action: async () => {
          const created = await apiFetch<NewConnectionResult>("connections", {
            method: "POST",
            body: { name: name.trim(), scopes: chosen, mode, webhook_url: notify ? notifyUrl.trim() : null },
          });
          setResult(created);
          setStep(3);
        },
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not connect the system.");
    } finally {
      setBusy(false);
    }
  }

  if (fresh.dialog && !result) return fresh.dialog;

  return (
    <Modal title={step === 3 ? "Your system is connected" : "Connect a system"} icon="add_link" onClose={onClose}>
      <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400" data-testid="connect-step">
        Step {step} of 3
      </p>
      {step === 1 && (
        <div>
          <label htmlFor="connection-name" className={labelClass}>
            What is the system called?
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
      )}
      {step === 2 && (
        <div className="flex flex-col gap-4">
          <fieldset>
            <legend className={labelClass}>What can it do?</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {ABILITIES.map((ability) => (
                <label
                  key={ability.scope}
                  className={cn(
                    "flex cursor-pointer items-start gap-2 rounded-xl border p-3 text-sm",
                    chosen.includes(ability.scope) ? "border-pine-green bg-pine-light/60" : "border-slate-200"
                  )}
                >
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={chosen.includes(ability.scope)}
                    onChange={() => toggle(ability.scope)}
                  />
                  <span>
                    <span className="block font-semibold text-slate-800">{ability.label}</span>
                    <span className="block text-[11px] text-slate-500">{ability.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          {notify && (
            <div>
              <label htmlFor="notify-url" className={labelClass}>
                Where should we send the notifications?
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
          <fieldset>
            <legend className={labelClass}>Live or test?</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {(
                [
                  ["live", "Live", "Real patient records"],
                  ["test", "Test", "Checks everything, saves nothing"],
                ] as const
              ).map(([value, label, hint]) => (
                <label
                  key={value}
                  className={cn(
                    "flex cursor-pointer items-start gap-2 rounded-xl border p-3 text-sm",
                    mode === value ? "border-pine-green bg-pine-light/60" : "border-slate-200"
                  )}
                >
                  <input type="radio" name="mode" className="mt-0.5" checked={mode === value} onChange={() => setMode(value)} />
                  <span>
                    <span className="block font-semibold text-slate-800">{label}</span>
                    <span className="block text-[11px] text-slate-500">{hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
        </div>
      )}
      {step === 3 && result && <Done result={result} />}
      <FormError message={error} />
      <div className="flex justify-end gap-2">
        {step === 2 && (
          <button type="button" className={secondaryButtonClass} onClick={() => setStep(1)}>
            Back
          </button>
        )}
        {step < 3 ? (
          <button type="button" className={primaryButtonClass} onClick={next} disabled={busy}>
            {step === 2 ? "Connect" : "Next"}
          </button>
        ) : (
          <button type="button" className={primaryButtonClass} onClick={onClose}>
            I saved the secret
          </button>
        )}
      </div>
    </Modal>
  );
}

function Done({ result }: { result: NewConnectionResult }) {
  return (
    <div className="flex flex-col gap-4" data-testid="connect-done">
      <div role="alert" className="flex gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
        <Icon name="warning" className="text-[18px]" />
        <span>
          <strong>Save the secret now.</strong> It is shown only this once: Endod keeps no readable copy. If it is
          lost, make a new one under Advanced.
        </span>
      </div>
      <CopyField label="Client ID" value={result.connection.client_id} testId="client-id" />
      <CopyField label="Client secret" value={result.client_secret} testId="client-secret" secret />
      {result.webhook_secret && (
        <CopyField label="Notification signing secret" value={result.webhook_secret} testId="notify-secret" secret />
      )}
      <a
        href={`/connect/${result.connection.id}/setup-guide`}
        target="_blank"
        rel="noreferrer"
        className={cn(secondaryButtonClass, "self-start")}
      >
        <Icon name="download" className="text-[16px]" />
        Download setup guide
      </a>
    </div>
  );
}
