"use client";

import { useEffect, useState, type FormEvent } from "react";
import QRCode from "qrcode";
import { hardNavigate } from "@/lib/navigation";
import { ApiError, apiFetch } from "@/lib/api";
import type { Staff } from "@/lib/api-types";
import { FormError, LoadingState, inputClass, labelClass, primaryButtonClass, secondaryButtonClass } from "@/components/common/states";

type Start = { secret: string; otpauth_uri: string; issuer: string; account: string };

/**
 * Two-step verification is required for staff of hospitals approved by Endod:
 * at the first sign-in they add the portal to an authenticator app (Google
 * Authenticator or any other), confirm a code, and receive 10 one-time
 * recovery codes, shown only here.
 */
export function EnrollForm() {
  const [start, setStart] = useState<Start | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const me = await apiFetch<Staff>("auth/me");
        if (me.stage === "full") return hardNavigate("/");
        if (me.stage === "totp") return hardNavigate("/login");
        if (me.must_change_password) return hardNavigate("/account/password");
        const value = await apiFetch<Start>("auth/enroll/start", { method: "POST" });
        const image = await QRCode.toDataURL(value.otpauth_uri, { errorCorrectionLevel: "M", margin: 1, width: 220 });
        if (!alive) return;
        setStart(value);
        setQr(image);
      } catch (err) {
        if (alive) setFatal(err instanceof ApiError ? err.message : "Could not start the set-up.");
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  async function confirm(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<{ recovery_codes: string[] }>("auth/enroll/confirm", {
        method: "POST",
        body: { code: code.replace(/\s/g, "") },
        redirectOn401: false,
      });
      setCodes(result.recovery_codes);
      setStart(null);
      setQr(null);
    } catch (err) {
      setCode("");
      if (err instanceof ApiError && err.status === 401) return hardNavigate("/login");
      setError(err instanceof ApiError ? err.message : "Could not check the code.");
    } finally {
      setBusy(false);
    }
  }

  function download() {
    const text = `Endod hospital portal: recovery codes\nEach code works once.\n\n${(codes ?? []).join("\n")}\n`;
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "endod-recovery-codes.txt";
    link.click();
    URL.revokeObjectURL(url);
  }

  if (fatal) {
    return (
      <div className="space-y-4">
        <FormError message={fatal} />
        <a href="/login" className="text-xs font-semibold text-pine-green hover:underline">
          Back to sign in
        </a>
      </div>
    );
  }

  if (codes) {
    return (
      <div className="space-y-4">
        <p className="text-xs text-slate-500">
          If you lose your phone, each of these codes signs you in once. They are shown only now: download or write
          them down and keep them safe.
        </p>
        <ol data-testid="recovery-codes" className="grid grid-cols-2 gap-2 rounded-xl bg-surface-container-low p-4 font-mono text-sm">
          {codes.map((value) => (
            <li key={value} data-testid="recovery-code">
              {value}
            </li>
          ))}
        </ol>
        <div className="flex gap-2">
          <button type="button" onClick={download} className={secondaryButtonClass}>
            Download .txt
          </button>
          <button type="button" onClick={() => void navigator.clipboard?.writeText(codes.join("\n"))} className={secondaryButtonClass}>
            Copy
          </button>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
          I have saved my recovery codes
        </label>
        <button type="button" disabled={!saved} onClick={() => hardNavigate("/")} className={`${primaryButtonClass} w-full py-2.5`}>
          Continue to the portal
        </button>
      </div>
    );
  }

  if (!start) return <LoadingState label="Preparing…" />;

  return (
    <form onSubmit={confirm} className="space-y-4">
      <p className="text-xs text-slate-500">
        Two-step verification is required. Scan this QR code with Google Authenticator (or any authenticator app),
        then enter the 6-digit code it shows.
      </p>
      <div className="flex justify-center">
        {qr && (
          // A data: URL made in the browser: nothing is sent to an image service.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={qr} alt="QR code for the Endod hospital portal" width={220} height={220} data-testid="totp-qr" className="rounded-lg" />
        )}
      </div>
      <div className="rounded-xl bg-surface-container-low p-3">
        <p className={labelClass}>Or enter this key</p>
        <p data-testid="totp-secret" className="mt-1 break-all font-mono text-xs">
          {start.secret.replace(/(.{4})/g, "$1 ").trim()}
        </p>
        <p className="mt-1 text-[11px] text-slate-500">
          Account {start.account} · issuer {start.issuer} · time-based, 6 digits
        </p>
      </div>
      <div>
        <label htmlFor="enroll-code" className={labelClass}>
          Code from the app
        </label>
        <input
          id="enroll-code"
          autoFocus
          value={code}
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="123456"
          onChange={(e) => setCode(e.target.value.replace(/[^\d ]/g, "").slice(0, 7))}
          className={`${inputClass} font-mono tracking-[0.3em]`}
        />
      </div>
      <FormError message={error} />
      <button type="submit" disabled={busy || code.replace(/\s/g, "").length !== 6} className={`${primaryButtonClass} w-full py-2.5`}>
        {busy ? "Checking…" : "Confirm and continue"}
      </button>
    </form>
  );
}
