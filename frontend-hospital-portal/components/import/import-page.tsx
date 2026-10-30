"use client";

import { useState } from "react";
import { Icon } from "@/components/ui/icon";
import { FormError, RoleGate, primaryButtonClass, secondaryButtonClass } from "@/components/common/states";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { useSignedIn } from "@/components/session/session-context";
import { ApiError, apiFetch, apiUpload } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { CATEGORY_LABELS, IMPORTERS, formatSize, type ImportPreview } from "@/lib/history-types";

const MAX_IMPORT_BYTES = 10 * 1024 * 1024;

type Result = { import_id: string; imported: number; skipped: { index: number; what: string; reason: string }[] };

export function ImportPage() {
  return (
    <RoleGate roles={IMPORTERS} what="importing records">
      <Loaded />
    </RoleGate>
  );
}

function Loaded() {
  const signedIn = useSignedIn();
  const { showToast } = useDashboard();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!signedIn) return null;
  const timeZone = signedIn.hospital.timezone;

  function choose(list: FileList | null) {
    const chosen = list?.[0] ?? null;
    setPreview(null);
    setResult(null);
    setError(null);
    if (chosen && chosen.size > MAX_IMPORT_BYTES) {
      setError("An import file can be at most 10 MB.");
      setFile(null);
      return;
    }
    setFile(chosen);
  }

  async function makePreview() {
    if (!file) return setError("Choose a FHIR bundle (.json) or a CSV file.");
    setBusy(true);
    setError(null);
    try {
      setPreview(await apiUpload<ImportPreview>("imports/preview", file));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not read the file.");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      const done = await apiFetch<Result>(`imports/${preview.import_id}/confirm`, { method: "POST" });
      setResult(done);
      setPreview(null);
      setFile(null);
      showToast(`${done.imported} record${done.imported === 1 ? "" : "s"} imported`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not import.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex w-full flex-col gap-5">
      <header>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-outline">Records</p>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Import records</h1>
        <p className="mt-0.5 max-w-3xl text-xs text-slate-500">
          Bring records from your own system into patients&apos; Endod history: a FHIR R4 Bundle (JSON) or a CSV file
          following the template. Each record must belong to a patient linked to Endod, matched by MRN or Endod ID.
          You see what will be imported, and what is skipped and why, before anything is saved. At most 10 MB and
          500 records per file.
        </p>
      </header>

      <section className="flex flex-col gap-3 rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label htmlFor="import-file" className="mb-1 block text-xs font-semibold text-on-surface-variant">File</label>
            <input id="import-file" type="file" accept=".json,.csv,application/json,application/fhir+json,text/csv"
              onChange={(e) => { choose(e.target.files); e.target.value = ""; }}
              className="block w-full text-xs text-slate-600 file:mr-3 file:rounded-xl file:border-0 file:bg-surface-container file:px-3 file:py-2 file:text-xs file:font-semibold" />
            {file && <p className="mt-1 text-[11px] text-slate-500">{file.name} ({formatSize(file.size)})</p>}
          </div>
          <button type="button" disabled={busy || !file} onClick={makePreview} className={primaryButtonClass}>
            <Icon name="preview" className="text-[16px]" />
            {busy && !preview ? "Reading…" : "Preview"}
          </button>
          <a href="/import-template.csv" download="endod-import-template.csv" className={secondaryButtonClass}>
            <Icon name="download" className="text-[16px]" />
            CSV template
          </a>
        </div>
        <FormError message={error} />
      </section>

      {preview && (
        <section data-testid="import-preview" className="flex flex-col gap-4 rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
          <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
            <h2 className="text-sm font-bold text-slate-800">
              {preview.items.length} to import, {preview.skipped.length} skipped ({preview.format === "fhir" ? "FHIR bundle" : "CSV"})
            </h2>
            <div className="flex gap-2">
              <button type="button" onClick={() => setPreview(null)} className={secondaryButtonClass}>Discard</button>
              <button type="button" disabled={busy || preview.items.length === 0} onClick={confirm} className={primaryButtonClass}>
                {busy ? "Importing…" : `Import ${preview.items.length} record${preview.items.length === 1 ? "" : "s"}`}
              </button>
            </div>
          </div>
          {preview.items.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-xs">
                <thead className="text-slate-500">
                  <tr>
                    <th className="py-1 pr-3">Item</th>
                    <th className="py-1 pr-3">Patient</th>
                    <th className="py-1 pr-3">Category</th>
                    <th className="py-1 pr-3">Title</th>
                    <th className="py-1 pr-3">When</th>
                    <th className="py-1 pr-3">File</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.items.map((item) => (
                    <tr key={item.index} data-testid="import-item" className="border-t border-slate-100">
                      <td className="py-1.5 pr-3 text-slate-500">{item.what}</td>
                      <td className="py-1.5 pr-3">{item.patient}</td>
                      <td className="py-1.5 pr-3">{CATEGORY_LABELS[item.category] ?? item.category}</td>
                      <td className="py-1.5 pr-3 font-semibold">{item.title}</td>
                      <td className="py-1.5 pr-3">{formatDateTime(item.occurred_at, timeZone)}</td>
                      <td className="py-1.5 pr-3">{item.file ? `${item.file.filename} (${formatSize(item.file.size)})` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <SkippedList skipped={preview.skipped} />
        </section>
      )}

      {result && (
        <section data-testid="import-result" className="flex flex-col gap-3 rounded-3xl border border-neutral-100 bg-neutral-50/50 p-5">
          <p className="text-sm font-bold text-neutral-900">
            Imported {result.imported} record{result.imported === 1 ? "" : "s"}. Linked patients see them in their Endod app.
          </p>
          <SkippedList skipped={result.skipped} />
        </section>
      )}
    </div>
  );
}

function SkippedList({ skipped }: { skipped: { index: number; what: string; reason: string }[] }) {
  if (skipped.length === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-xs font-bold text-amber-900">Skipped</h3>
      <ul className="flex flex-col gap-1">
        {skipped.map((s) => (
          <li key={`${s.index}-${s.what}`} data-testid="import-skipped" className="rounded-xl bg-amber-50 px-3 py-1.5 text-xs text-amber-900">
            <strong>{s.what}:</strong> {s.reason}
          </li>
        ))}
      </ul>
    </div>
  );
}
