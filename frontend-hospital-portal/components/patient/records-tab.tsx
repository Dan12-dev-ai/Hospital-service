"use client";

import { useState } from "react";
import { Icon } from "@/components/ui/icon";
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
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { DispensingPanel } from "@/components/patient/dispensing";
import { FileLinks, RecordDetails } from "@/components/patient/record-details";
import { RecordForm } from "@/components/patient/record-form";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import type { Hospital, Role, Staff } from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import {
  CATEGORY_ICONS,
  CATEGORY_LABELS,
  DOCUMENT_CATEGORIES,
  DOCUMENT_FILERS,
  RECORD_WRITERS,
  categoriesFor,
  type ClinicalRecord,
  type RecordCategory,
  type RecordList,
  type Visit,
} from "@/lib/history-types";

function mayWrite(role: Role, category: RecordCategory): boolean {
  return RECORD_WRITERS.includes(role) || (DOCUMENT_FILERS.includes(role) && DOCUMENT_CATEGORIES.includes(category));
}

/** A patient's clinical records: newest first, with their files; add and retract. */
export function RecordsTab({ patientId, staff, hospital }: { patientId: string; staff: Staff; hospital: Hospital }) {
  const { showToast } = useDashboard();
  const records = useApi<RecordList>(`patients/${patientId}/records`);
  const visits = useApi<Visit[]>(`patients/${patientId}/visits`);
  const [adding, setAdding] = useState(false);
  const [retracting, setRetracting] = useState<ClinicalRecord | null>(null);
  const [correcting, setCorrecting] = useState<ClinicalRecord | null>(null);
  const [filter, setFilter] = useState<RecordCategory | "all">("all");
  const categories = categoriesFor(staff.role);

  if (records.error) return <ErrorState message={records.error.message} onRetry={records.reload} />;
  if (!records.data) return <LoadingState label="Loading records…" />;
  const items = records.data.items.filter((r) => filter === "all" || r.category === filter);

  return (
    <div className="flex flex-col gap-4 rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div className="flex items-center gap-2">
          <label htmlFor="records-filter" className="text-xs font-semibold text-slate-500">Show</label>
          <select id="records-filter" value={filter} onChange={(e) => setFilter(e.target.value as RecordCategory | "all")}
            className="rounded-lg bg-surface-container-low px-2 py-1 text-xs">
            <option value="all">All records</option>
            {(Object.keys(CATEGORY_LABELS) as RecordCategory[]).map((c) => (
              <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>
            ))}
          </select>
        </div>
        {categories.length > 0 && (
          <button type="button" onClick={() => setAdding(true)} className={primaryButtonClass}>
            <Icon name="note_add" className="text-[16px]" />
            Add record
          </button>
        )}
      </div>
      {!records.data.linked && (
        <p className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500">
          This patient is not linked to Endod: records stay in this hospital. Once linked, they are sent to the
          patient&apos;s Endod app.
        </p>
      )}

      {items.length === 0 ? (
        <EmptyState icon="folder_open" title={filter === "all" ? "No records yet" : `No ${CATEGORY_LABELS[filter].toLowerCase()} records`} />
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((r) => (
            <li key={r.id} data-testid="record-card"
              className={`flex flex-col gap-2 rounded-2xl border px-4 py-3 ${r.retracted ? "border-rose-100 bg-rose-50/40" : "border-slate-100"}`}>
              <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-start">
                <div className="flex items-start gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-pine-light text-pine-green">
                    <Icon name={CATEGORY_ICONS[r.category]} className="text-[18px]" />
                  </div>
                  <div className="flex flex-col">
                    <span className={`text-sm font-bold text-slate-800 ${r.retracted ? "line-through" : ""}`}>{r.title}</span>
                    <span className="text-[11px] text-slate-500">
                      {CATEGORY_LABELS[r.category]} • {formatDateTime(r.occurred_at, hospital.timezone)}
                      {r.recorded_by ? ` • ${r.recorded_by}` : ""}
                      {r.source === "import" ? " • imported" : ""}
                    </span>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {r.version > 1 && (
                    <span data-testid="record-corrected" className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
                      Corrected • version {r.version}
                    </span>
                  )}
                  {r.published && (
                    <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">Sent to Endod</span>
                  )}
                  {r.retracted ? (
                    <span className="rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-semibold text-rose-800">Retracted</span>
                  ) : (
                    mayWrite(staff.role, r.category) && (
                      <>
                        <button type="button" onClick={() => setCorrecting(r)} className={secondaryButtonClass}>
                          <Icon name="edit_note" className="text-[16px]" />
                          Edit / correct
                        </button>
                        <button type="button" onClick={() => setRetracting(r)} className={secondaryButtonClass}>
                          Retract
                        </button>
                      </>
                    )
                  )}
                </div>
              </div>
              {r.retracted && r.retracted_reason && (
                <p className="text-xs text-rose-800">Entered in error: {r.retracted_reason}</p>
              )}
              <RecordDetails details={r.details} />
              <FileLinks files={r.files} base={`records/${r.id}/files`} />
              {r.category === "prescription" && r.dispensing && (
                <DispensingPanel dispensing={r.dispensing} timeZone={hospital.timezone} />
              )}
            </li>
          ))}
        </ul>
      )}

      {adding && (
        <RecordForm
          patientId={patientId}
          categories={categories}
          visits={visits.data ?? []}
          onClose={() => setAdding(false)}
          onSaved={(record) => {
            setAdding(false);
            showToast(record.published ? "Record saved and sent to Endod" : "Record saved");
            records.reload();
          }}
        />
      )}
      {correcting && (
        <RecordForm
          patientId={patientId}
          categories={categories}
          visits={visits.data ?? []}
          record={correcting}
          onClose={() => setCorrecting(null)}
          onSaved={(record) => {
            setCorrecting(null);
            showToast(record.published
              ? `Correction saved as version ${record.version} and sent to Endod`
              : `Correction saved as version ${record.version}`);
            records.reload();
          }}
        />
      )}
      {retracting && (
        <RetractModal
          record={retracting}
          onClose={() => setRetracting(null)}
          onDone={() => {
            setRetracting(null);
            showToast("Record retracted");
            records.reload();
          }}
        />
      )}
    </div>
  );
}

function RetractModal({ record, onClose, onDone }: { record: ClinicalRecord; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (reason.trim().length < 2) {
      setError("Say why the record is retracted.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`records/${record.id}/retract`, { method: "POST", body: { reason: reason.trim() } });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not retract the record.");
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Retract record"
      icon="undo"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButtonClass}>Cancel</button>
          <button type="button" disabled={busy} onClick={submit} className={dangerButtonClass}>
            {busy ? "Retracting…" : "Retract"}
          </button>
        </>
      }
    >
      <p className="text-xs text-slate-600">
        &ldquo;{record.title}&rdquo; stays in the hospital&apos;s history, marked as entered in error, and is withdrawn
        from the patient&apos;s Endod app.
      </p>
      <div>
        <label htmlFor="retract-reason" className={labelClass}>Reason</label>
        <input id="retract-reason" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} className={inputClass} />
      </div>
      <FormError message={error} />
    </Modal>
  );
}
