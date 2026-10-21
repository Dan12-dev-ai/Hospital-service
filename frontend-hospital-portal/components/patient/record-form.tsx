"use client";

import { useRef, useState, type ReactNode } from "react";
import { Icon } from "@/components/ui/icon";
import {
  FormError,
  Modal,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { ApiError, apiFetch, apiUpload } from "@/lib/api";
import {
  ACCEPTED_FILES,
  CATEGORY_LABELS,
  MAX_FILE_BYTES,
  MAX_FILES_PER_RECORD,
  formatSize,
  type ClinicalRecord,
  type RecordCategory,
  type RecordFile,
  type Visit,
} from "@/lib/history-types";

type Row = Record<string, string>;

const PRESCRIPTION_FIELDS = [
  ["drug", "Medicine"],
  ["dose", "Dose"],
  ["route", "Route"],
  ["frequency", "Frequency"],
  ["duration", "Duration"],
  ["quantity", "Quantity"],
] as const;
const LAB_FIELDS = [
  ["test", "Test"],
  ["value", "Value"],
  ["unit", "Unit"],
  ["reference_range", "Reference range"],
] as const;
const VITALS = [
  ["bp", "BP"],
  ["pulse", "Pulse"],
  ["temp", "Temp (°C)"],
  ["weight", "Weight (kg)"],
  ["height", "Height (cm)"],
  ["spo2", "SpO₂ (%)"],
] as const;

function blank(value: string): string | null {
  return value.trim() || null;
}

/** "2026-10-21T09:30" for a datetime-local input, in the browser's time. */
function localNow(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 16);
}

/** The details object the backend expects for the category (docs/history-events.md, section 2). */
export function buildDetails(category: RecordCategory, fields: Row, items: Row[], vitals: Row): Record<string, unknown> {
  switch (category) {
    case "diagnosis":
      return { condition: blank(fields.condition ?? ""), code: blank(fields.code ?? ""), status: fields.status || "active", notes: blank(fields.notes ?? "") };
    case "prescription":
      return {
        items: items
          .filter((row) => (row.drug ?? "").trim())
          .map((row) => Object.fromEntries(PRESCRIPTION_FIELDS.map(([key]) => [key, blank(row[key] ?? "")]))),
        notes: blank(fields.notes ?? ""),
      };
    case "lab_result":
      return {
        items: items
          .filter((row) => (row.test ?? "").trim())
          .map((row) => ({
            ...Object.fromEntries(LAB_FIELDS.map(([key]) => [key, blank(row[key] ?? "")])),
            flag: row.flag || null,
          })),
        specimen: blank(fields.specimen ?? ""),
        notes: blank(fields.notes ?? ""),
      };
    case "imaging":
      return { modality: blank(fields.modality ?? ""), body_part: blank(fields.body_part ?? ""), findings: blank(fields.findings ?? ""), impression: blank(fields.impression ?? "") };
    case "visit_note":
      return {
        complaint: blank(fields.complaint ?? ""),
        findings: blank(fields.findings ?? ""),
        plan: blank(fields.plan ?? ""),
        vitals: Object.fromEntries(VITALS.map(([key]) => [key, blank(vitals[key] ?? "")])),
      };
    case "document":
      return { description: blank(fields.description ?? "") };
  }
}

/** "2026-10-21T09:30" for a datetime-local input, from an ISO time, in the browser's time. */
function localInput(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return localNow();
  when.setMinutes(when.getMinutes() - when.getTimezoneOffset());
  return when.toISOString().slice(0, 16);
}

function asText(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function asRow(value: unknown): Row {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value).map(([key, v]) => [key, asText(v)]));
}

/** The form's state from a saved record's details (the reverse of buildDetails). */
export function formFromDetails(category: RecordCategory, details: unknown): { fields: Row; items: Row[]; vitals: Row } {
  const all = asRow(details);
  const raw = typeof details === "object" && details !== null ? (details as Record<string, unknown>) : {};
  const items = Array.isArray(raw.items) ? raw.items.map(asRow).filter((row) => Object.keys(row).length > 0) : [];
  return {
    fields: category === "diagnosis" ? { ...all, status: all.status || "active" } : all,
    items: items.length > 0 ? items : [{}],
    vitals: asRow(raw.vitals),
  };
}

/**
 * Adds a clinical record: the category's fields, optional visit, and files
 * (uploaded one by one, then attached). With ``record``, corrects that record
 * instead: the same fields, filled in, saved as a new version (and sent to
 * Endod again when the patient is linked).
 */
export function RecordForm({
  patientId,
  categories,
  visits,
  record,
  onClose,
  onSaved,
}: {
  patientId: string;
  categories: RecordCategory[];
  visits: Visit[];
  /** The record to correct (its category cannot change). */
  record?: ClinicalRecord;
  onClose: () => void;
  onSaved: (record: ClinicalRecord) => void;
}) {
  const initial = record ? formFromDetails(record.category, record.details) : null;
  const [category, setCategory] = useState<RecordCategory>(record?.category ?? categories[0]);
  const [title, setTitle] = useState(record?.title ?? "");
  const [occurredAt, setOccurredAt] = useState(() => (record ? localInput(record.occurred_at) : localNow()));
  const [visitId, setVisitId] = useState("");
  const [fields, setFields] = useState<Row>(initial?.fields ?? { status: "active" });
  const [items, setItems] = useState<Row[]>(initial?.items ?? [{}]);
  const [vitals, setVitals] = useState<Row>(initial?.vitals ?? {});
  const [files, setFiles] = useState<File[]>([]);
  // Files the record already has, and those the correction removes.
  const [removed, setRemoved] = useState<string[]>([]);
  const kept = (record?.files ?? []).filter((f) => !removed.includes(f.id));
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Files already uploaded (a retry after an error does not send them again).
  const uploaded = useRef(new Map<File, string>());

  function field(key: string, label: string, options: { area?: boolean; placeholder?: string } = {}) {
    const id = `record-${key}`;
    return (
      <div className={options.area ? "sm:col-span-2" : undefined}>
        <label htmlFor={id} className={labelClass}>{label}</label>
        {options.area ? (
          <textarea id={id} rows={2} value={fields[key] ?? ""} placeholder={options.placeholder}
            onChange={(e) => setFields((f) => ({ ...f, [key]: e.target.value }))} className={inputClass} />
        ) : (
          <input id={id} value={fields[key] ?? ""} placeholder={options.placeholder}
            onChange={(e) => setFields((f) => ({ ...f, [key]: e.target.value }))} className={inputClass} />
        )}
      </div>
    );
  }

  function setItem(index: number, key: string, value: string) {
    setItems((rows) => rows.map((row, i) => (i === index ? { ...row, [key]: value } : row)));
  }

  function chooseFiles(list: FileList | null) {
    const chosen = Array.from(list ?? []);
    const tooBig = chosen.find((f) => f.size > MAX_FILE_BYTES);
    if (tooBig) {
      setError(`${tooBig.name} is larger than 20 MB.`);
      return;
    }
    const next = [...files, ...chosen];
    if (next.length + kept.length > MAX_FILES_PER_RECORD) {
      setError(`A record can have at most ${MAX_FILES_PER_RECORD} files.`);
      return;
    }
    setError(null);
    setFiles(next);
  }

  async function save() {
    if (title.trim().length < 2) return setError("Give the record a title.");
    if (category === "document" && files.length === 0 && kept.length === 0) return setError("Attach the document's file.");
    const when = new Date(occurredAt);
    if (Number.isNaN(when.getTime())) return setError("Enter when it happened.");
    setBusy(true);
    setError(null);
    try {
      const fileIds: string[] = [];
      for (const [index, file] of files.entries()) {
        const done = uploaded.current.get(file);
        if (done) {
          fileIds.push(done);
          continue;
        }
        setProgress(`Uploading ${file.name} (${index + 1} of ${files.length})…`);
        const stored = await apiUpload<RecordFile>(`patients/${patientId}/uploads`, file);
        uploaded.current.set(file, stored.id);
        fileIds.push(stored.id);
      }
      setProgress(record ? "Saving the correction…" : "Saving the record…");
      const details = buildDetails(category, fields, items, vitals);
      const saved = record
        ? await apiFetch<ClinicalRecord>(`records/${record.id}`, {
            method: "PATCH",
            body: {
              title: title.trim(),
              details,
              occurred_at: when.toISOString(),
              add_file_ids: fileIds,
              remove_file_ids: removed,
            },
          })
        : await apiFetch<ClinicalRecord>(`patients/${patientId}/records`, {
            method: "POST",
            body: {
              category,
              title: title.trim(),
              details,
              occurred_at: when.toISOString(),
              visit_id: visitId || null,
              file_ids: fileIds,
            },
          });
      onSaved(saved);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the record.");
      setBusy(false);
      setProgress(null);
    }
  }

  let body: ReactNode = null;
  if (category === "diagnosis") {
    body = (
      <>
        {field("condition", "Condition")}
        {field("code", "ICD-10 code (optional)", { placeholder: "B50.9" })}
        <div>
          <label htmlFor="record-status" className={labelClass}>Status</label>
          <select id="record-status" value={fields.status ?? "active"} onChange={(e) => setFields((f) => ({ ...f, status: e.target.value }))} className={inputClass}>
            <option value="active">Active</option>
            <option value="chronic">Chronic</option>
            <option value="resolved">Resolved</option>
          </select>
        </div>
        {field("notes", "Notes", { area: true })}
      </>
    );
  } else if (category === "prescription" || category === "lab_result") {
    const columns = category === "prescription" ? PRESCRIPTION_FIELDS : LAB_FIELDS;
    body = (
      <>
        <div className="flex flex-col gap-2 sm:col-span-2">
          {items.map((row, index) => (
            <fieldset key={index} className="grid grid-cols-2 gap-2 rounded-2xl bg-surface-container-low/60 p-3 sm:grid-cols-3">
              <legend className="sr-only">{category === "prescription" ? `Medicine ${index + 1}` : `Test ${index + 1}`}</legend>
              {columns.map(([key, label]) => (
                <div key={key}>
                  <label htmlFor={`item-${index}-${key}`} className={labelClass}>{label}</label>
                  <input id={`item-${index}-${key}`} value={row[key] ?? ""} onChange={(e) => setItem(index, key, e.target.value)} className={inputClass} />
                </div>
              ))}
              {category === "lab_result" && (
                <div>
                  <label htmlFor={`item-${index}-flag`} className={labelClass}>Flag</label>
                  <select id={`item-${index}-flag`} value={row.flag ?? ""} onChange={(e) => setItem(index, "flag", e.target.value)} className={inputClass}>
                    <option value="">—</option>
                    <option value="low">Low</option>
                    <option value="normal">Normal</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                  </select>
                </div>
              )}
            </fieldset>
          ))}
          <button type="button" onClick={() => setItems((rows) => [...rows, {}])} className={`${secondaryButtonClass} self-start`}>
            <Icon name="add" className="text-[16px]" />
            {category === "prescription" ? "Add medicine" : "Add test"}
          </button>
        </div>
        {category === "lab_result" && field("specimen", "Specimen")}
        {field("notes", "Notes", { area: true })}
      </>
    );
  } else if (category === "imaging") {
    body = (
      <>
        {field("modality", "Modality", { placeholder: "X-ray, CT, MRI, ultrasound" })}
        {field("body_part", "Body part")}
        {field("findings", "Findings", { area: true })}
        {field("impression", "Impression", { area: true })}
      </>
    );
  } else if (category === "visit_note") {
    body = (
      <>
        {field("complaint", "Complaint", { area: true })}
        {field("findings", "Findings", { area: true })}
        {field("plan", "Plan", { area: true })}
        <div className="grid grid-cols-3 gap-2 sm:col-span-2">
          {VITALS.map(([key, label]) => (
            <div key={key}>
              <label htmlFor={`vital-${key}`} className={labelClass}>{label}</label>
              <input id={`vital-${key}`} value={vitals[key] ?? ""} onChange={(e) => setVitals((v) => ({ ...v, [key]: e.target.value }))} className={inputClass} />
            </div>
          ))}
        </div>
      </>
    );
  } else {
    body = field("description", "Description", { area: true });
  }

  return (
    <Modal
      title={record ? "Correct record" : "Add record"}
      icon={record ? "edit_note" : "note_add"}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButtonClass}>Cancel</button>
          <button type="button" disabled={busy} onClick={save} className={primaryButtonClass}>
            {busy ? "Saving…" : record ? "Save correction" : "Save record"}
          </button>
        </>
      }
    >
      {record && (
        <p className="text-xs text-slate-600">
          The correction is saved as version {record.version + 1}; the earlier version stays in the record&apos;s
          history{record.published || record.published_version ? ", and Endod is sent the corrected version" : ""}.
        </p>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="record-category" className={labelClass}>Category</label>
          <select id="record-category" value={category} disabled={Boolean(record)}
            onChange={(e) => { setCategory(e.target.value as RecordCategory); setItems([{}]); }} className={inputClass}>
            {(record ? [record.category] : categories).map((c) => (
              <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="record-when" className={labelClass}>When</label>
          <input id="record-when" type="datetime-local" value={occurredAt} onChange={(e) => setOccurredAt(e.target.value)} className={inputClass} />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor="record-title" className={labelClass}>Title</label>
          <input id="record-title" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} className={inputClass} />
        </div>
        {!record && visits.length > 0 && (
          <div className="sm:col-span-2">
            <label htmlFor="record-visit" className={labelClass}>Visit (optional)</label>
            <select id="record-visit" value={visitId} onChange={(e) => setVisitId(e.target.value)} className={inputClass}>
              <option value="">No visit</option>
              {visits.map((v) => (
                <option key={v.id} value={v.id}>
                  {new Date(v.started_at).toLocaleDateString("en-GB")} {v.doctor?.full_name ? `• ${v.doctor.full_name}` : ""}
                </option>
              ))}
            </select>
          </div>
        )}
        {body}
        <div className="sm:col-span-2">
          <label htmlFor="record-files" className={labelClass}>Files (PDF, JPEG, PNG or WebP; up to 10, 20 MB each)</label>
          <input id="record-files" type="file" multiple accept={ACCEPTED_FILES} onChange={(e) => { chooseFiles(e.target.files); e.target.value = ""; }}
            className="block w-full text-xs text-slate-600 file:mr-3 file:rounded-xl file:border-0 file:bg-surface-container file:px-3 file:py-2 file:text-xs file:font-semibold" />
          {kept.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1" data-testid="kept-files">
              {kept.map((file) => (
                <li key={file.id} className="flex items-center justify-between rounded-xl bg-surface-container-low px-3 py-1.5 text-xs">
                  <span className="truncate">{file.filename} <span className="text-slate-400">({formatSize(file.size)}, attached)</span></span>
                  <button type="button" aria-label={`Remove ${file.filename}`} onClick={() => setRemoved((ids) => [...ids, file.id])} className="text-slate-400 hover:text-rose-600">
                    <Icon name="close" className="text-[16px]" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {files.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1" data-testid="chosen-files">
              {files.map((file, index) => (
                <li key={`${file.name}-${index}`} className="flex items-center justify-between rounded-xl bg-surface-container-low px-3 py-1.5 text-xs">
                  <span className="truncate">{file.name} <span className="text-slate-400">({formatSize(file.size)})</span></span>
                  <button type="button" aria-label={`Remove ${file.name}`} onClick={() => setFiles((list) => list.filter((_, i) => i !== index))} className="text-slate-400 hover:text-rose-600">
                    <Icon name="close" className="text-[16px]" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      {progress && <p className="text-xs text-slate-500" role="status">{progress}</p>}
      <FormError message={error} />
    </Modal>
  );
}
