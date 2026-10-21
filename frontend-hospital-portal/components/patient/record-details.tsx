"use client";

import { Icon } from "@/components/ui/icon";
import { fileUrl } from "@/lib/api";
import { formatSize } from "@/lib/history-types";
import { titleCase } from "@/lib/format";

type Value = unknown;

function text(value: Value): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

function Pairs({ entries }: { entries: [string, Value][] }) {
  const shown = entries.filter(([, v]) => text(v) !== null);
  if (shown.length === 0) return null;
  return (
    <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
      {shown.map(([key, value]) => (
        <div key={key} className="flex gap-1.5">
          <dt className="shrink-0 font-semibold text-slate-500">{titleCase(key)}:</dt>
          <dd className="whitespace-pre-line text-slate-800">{text(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A record's details, whatever the category: fields, item tables and vitals. Read-only. */
export function RecordDetails({ details }: { details: Record<string, unknown> }) {
  const items = Array.isArray(details.items) ? (details.items as Record<string, Value>[]) : [];
  const vitals = details.vitals && typeof details.vitals === "object" ? (details.vitals as Record<string, Value>) : null;
  const rest = Object.entries(details).filter(([key]) => key !== "items" && key !== "vitals");
  const columns = Array.from(new Set(items.flatMap((item) => Object.keys(item ?? {})))).filter((key) =>
    items.some((item) => text(item?.[key]) !== null)
  );
  return (
    <div className="flex flex-col gap-2">
      {items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-left text-xs">
            <thead>
              <tr className="text-slate-500">
                {columns.map((key) => (
                  <th key={key} className="py-1 pr-3 font-semibold">{titleCase(key)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((item, index) => (
                <tr key={index} className="border-t border-slate-100">
                  {columns.map((key) => (
                    <td key={key} className={`py-1 pr-3 ${key === "flag" && item[key] && item[key] !== "normal" ? "font-bold text-rose-700" : "text-slate-800"}`}>
                      {text(item[key]) ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pairs entries={rest} />
      {vitals && <Pairs entries={Object.entries(vitals)} />}
    </div>
  );
}

/** A record's files, each opened (in a new tab) or saved through the portal's download route. */
export function FileLinks({ files, base }: { files: { id: string; filename: string; size: number; content_type: string }[]; base: string }) {
  if (files.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-2" data-testid="record-files">
      {files.map((file) => (
        <li key={file.id} className="flex items-center gap-2 rounded-xl bg-surface-container-low px-3 py-1.5 text-xs">
          <Icon name={file.content_type === "application/pdf" ? "picture_as_pdf" : "image"} className="text-[16px] text-pine-green" />
          <a href={fileUrl(`${base}/${file.id}`)} target="_blank" rel="noopener noreferrer" className="font-semibold text-primary hover:underline">
            {file.filename}
          </a>
          <span className="text-slate-400">{formatSize(file.size)}</span>
          <a href={fileUrl(`${base}/${file.id}`, true)} download={file.filename} aria-label={`Download ${file.filename}`} className="text-slate-500 hover:text-primary">
            <Icon name="download" className="text-[16px]" />
          </a>
        </li>
      ))}
    </ul>
  );
}
