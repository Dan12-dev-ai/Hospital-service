"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Icon } from "@/components/ui/icon";
import {
  ErrorState,
  FormError,
  LoadingState,
  dangerButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { QrScanner } from "@/components/patient/qr-scanner";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import type { LinkState } from "@/lib/history-types";
import { formatDateTime } from "@/lib/format";

const REFUSALS: Record<string, string> = {
  not_found: "Endod has no active account with this ID.",
  not_verified: "The phone number or the card did not match the Endod account.",
  already_linked: "This Endod ID is already linked to another patient here.",
};

/** The health card's QR: https://endod-health.com/card/<ID>?s=<signature>. */
export function looksLikeCardUrl(text: string): boolean {
  try {
    const url = new URL(text.trim());
    return url.protocol === "https:" && /^(www\.)?endod-health\.com$/.test(url.hostname) && url.pathname.startsWith("/card/");
  } catch {
    return false;
  }
}

/**
 * Links the patient to their Endod account: by scanning the health card (the
 * camera, or a scanner that types the card's link), or by the Endod ID with
 * the account's phone number. Endod confirms or refuses; until then the
 * request shows as pending (this card checks every few seconds).
 */
export function EndodLink({
  patientId,
  canLink,
  timeZone,
  onChange,
}: {
  patientId: string;
  canLink: boolean;
  timeZone: string;
  /** Called when the patient becomes linked or unlinked. */
  onChange?: () => void;
}) {
  const { showToast } = useDashboard();
  const state = useApi<LinkState>(`patients/${patientId}/link`);
  const [mode, setMode] = useState<"card" | "id">("id");
  const [scanning, setScanning] = useState(false);
  const [cardUrl, setCardUrl] = useState("");
  const [dedanId, setDedanId] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = state.data?.request?.status === "pending" && !state.data.dedan_id;
  const { reload } = state;

  // Tell the page when the link itself changes (not on the first load).
  const linkedNow = state.data ? state.data.dedan_id ?? "" : null;
  const seen = useRef<string | null>(null);
  const notify = useRef(onChange);
  useEffect(() => {
    notify.current = onChange;
  }, [onChange]);
  useEffect(() => {
    if (linkedNow === null) return;
    if (seen.current !== null && seen.current !== linkedNow) notify.current?.();
    seen.current = linkedNow;
  }, [linkedNow]);

  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(reload, 4000);
    return () => clearInterval(timer);
  }, [pending, reload]);

  async function send(body: Record<string, string>) {
    setBusy(true);
    setError(null);
    try {
      await apiFetch<LinkState>(`patients/${patientId}/link`, { method: "POST", body });
      showToast("Sent to Endod for confirmation");
      setCardUrl("");
      reload();
    } catch (err) {
      // Refused (400, 409, ...): back to idle with the reason shown; scanning
      // again is one click away.
      setError(err instanceof ApiError ? err.message : "Could not send the request.");
    } finally {
      // Either way the scanner closes, so its camera is off.
      setScanning(false);
      setBusy(false);
    }
  }

  function submitId(event: FormEvent) {
    event.preventDefault();
    if (!/^DE-?\d{6}$/i.test(dedanId.trim().replace(/\s+/g, ""))) {
      setError("An Endod ID is DE and six digits, e.g. DE482731.");
      return;
    }
    if (!phone.trim()) {
      setError("Enter the phone number on the patient's Endod account.");
      return;
    }
    void send({ dedan_id: dedanId.trim(), phone: phone.trim() });
  }

  function submitCard(text: string) {
    if (!looksLikeCardUrl(text)) {
      setError("That is not an Endod health card. Scan the QR code on the card.");
      setScanning(false);
      return;
    }
    void send({ card_url: text.trim() });
  }

  async function unlink() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch<LinkState>(`patients/${patientId}/link`, { method: "DELETE" });
      showToast(state.data?.dedan_id ? "Unlinked from Endod" : "Request withdrawn");
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not unlink.");
    } finally {
      setBusy(false);
    }
  }

  if (state.error) return <ErrorState message={state.error.message} onRetry={reload} />;
  if (!state.data) return <LoadingState label="Loading the Endod link…" />;
  const { dedan_id: linkedId, request } = state.data;

  return (
    <section className="flex flex-col gap-4 rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
      <h2 className="flex items-center gap-2 text-sm font-bold text-slate-800">
        <Icon name="link" className="text-[18px] text-black" />
        Endod account
      </h2>

      {linkedId ? (
        <div data-testid="endod-link-status" className="flex flex-col gap-2 rounded-2xl bg-neutral-50 px-4 py-3 text-xs text-neutral-900 sm:flex-row sm:items-center sm:justify-between">
          <span>
            <strong>Linked to Endod {linkedId}</strong>
            {request?.status === "linked" && request.linked_name ? ` (${request.linked_name})` : ""}. New records and
            follow-ups are sent to the patient&apos;s Endod app.
          </span>
          {canLink && (
            <button type="button" disabled={busy} onClick={unlink} className={dangerButtonClass}>
              Unlink
            </button>
          )}
        </div>
      ) : pending && request ? (
        <div data-testid="endod-link-status" className="flex flex-col gap-2 rounded-2xl bg-sky-50 px-4 py-3 text-xs text-sky-900 sm:flex-row sm:items-center sm:justify-between">
          <span className="flex items-center gap-2">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-sky-600 border-t-transparent" />
            <span>
              <strong>Pending:</strong> waiting for Endod to confirm {request.dedan_id} (
              {request.method === "card" ? "health card" : "Endod ID and phone"}
              {request.created_at ? `, sent ${formatDateTime(request.created_at, timeZone)}` : ""}).
            </span>
          </span>
          {canLink && (
            <button type="button" disabled={busy} onClick={unlink} className={secondaryButtonClass}>
              Withdraw
            </button>
          )}
        </div>
      ) : (
        <>
          {request?.status === "refused" && (
            <p data-testid="endod-link-status" role="alert" className="rounded-2xl bg-rose-50 px-4 py-3 text-xs text-rose-800">
              <strong>Refused:</strong> {REFUSALS[request.reason ?? ""] ?? "Endod did not confirm the account."} (
              {request.dedan_id})
            </p>
          )}
          {!request || request.status !== "refused" ? (
            <p data-testid="endod-link-status" className="text-xs text-slate-500">
              Not linked. Once linked, this patient&apos;s records and follow-ups appear in their Endod app. Nothing is
              sent to Endod before the account is confirmed.
            </p>
          ) : null}
          {state.data.claimed_dedan_id && (
            <p data-testid="endod-claim" className="flex flex-wrap items-center gap-2 rounded-2xl bg-amber-50 px-4 py-2 text-xs text-amber-900">
              <span>
                <strong>Endod ID given, not yet linked:</strong> {state.data.claimed_dedan_id}. Link it below to
                confirm it with Endod.
              </span>
              {canLink && (
                <button type="button" onClick={() => { setMode("id"); setDedanId(state.data?.claimed_dedan_id ?? ""); }}
                  className="font-semibold text-black hover:underline">
                  Use this ID
                </button>
              )}
            </p>
          )}
          {canLink ? (
            <div className="flex flex-col gap-3">
              <div role="tablist" className="flex gap-2">
                <button type="button" role="tab" aria-selected={mode === "id"} onClick={() => { setMode("id"); setScanning(false); }}
                  className={mode === "id" ? primaryButtonClass : secondaryButtonClass}>
                  <Icon name="badge" className="text-[16px]" />
                  Endod ID and phone
                </button>
                <button type="button" role="tab" aria-selected={mode === "card"} onClick={() => setMode("card")}
                  className={mode === "card" ? primaryButtonClass : secondaryButtonClass}>
                  <Icon name="qr_code_scanner" className="text-[16px]" />
                  Scan health card
                </button>
              </div>
              {mode === "id" ? (
                <form onSubmit={submitId} className="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:items-end" noValidate>
                  <div>
                    <label htmlFor="link-dedan" className={labelClass}>Endod ID</label>
                    <input id="link-dedan" placeholder="DE482731" value={dedanId} onChange={(e) => setDedanId(e.target.value)} className={inputClass} />
                  </div>
                  <div>
                    <label htmlFor="link-phone" className={labelClass}>Phone on the Endod account</label>
                    <input id="link-phone" type="tel" placeholder="0911 234 567" value={phone} onChange={(e) => setPhone(e.target.value)} className={inputClass} />
                  </div>
                  <button type="submit" disabled={busy} className={`${primaryButtonClass} py-2.5`}>
                    {busy ? "Sending…" : "Link to Endod"}
                  </button>
                </form>
              ) : (
                <div className="flex flex-col gap-3">
                  {scanning ? (
                    <QrScanner onResult={submitCard} onClose={() => setScanning(false)} />
                  ) : (
                    <button type="button" disabled={busy} onClick={() => { setError(null); setScanning(true); }} className={secondaryButtonClass}>
                      <Icon name="photo_camera" className="text-[16px]" />
                      {error ? "Scan again" : "Open the camera"}
                    </button>
                  )}
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      submitCard(cardUrl);
                    }}
                    className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto] sm:items-end"
                  >
                    <div>
                      <label htmlFor="link-card" className={labelClass}>Or the card&apos;s link (a QR scanner types it here)</label>
                      <input id="link-card" placeholder="https://endod-health.com/card/…" value={cardUrl} onChange={(e) => setCardUrl(e.target.value)} className={inputClass} />
                    </div>
                    <button type="submit" disabled={busy || !cardUrl.trim()} className={`${primaryButtonClass} py-2.5`}>
                      Link with card
                    </button>
                  </form>
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-slate-500">Reception or records staff link patients to Endod.</p>
          )}
        </>
      )}
      <FormError message={error} />
    </section>
  );
}
