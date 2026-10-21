"use client";

import Link from "next/link";
import { Icon } from "@/components/ui/icon";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { FileLinks, RecordDetails } from "@/components/patient/record-details";
import { useApi } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { CATEGORY_ICONS, CATEGORY_LABELS, type Share } from "@/lib/history-types";

/**
 * Records patients shared with this hospital from their Endod app: read-only,
 * each showing where it came from. Files are fetched from Endod when opened.
 */
export function SharedList({
  path,
  timeZone,
  showPatient,
  empty,
}: {
  path: string;
  timeZone: string;
  showPatient: boolean;
  empty: string;
}) {
  const shares = useApi<{ items: Share[] }>(path);

  if (shares.error) return <ErrorState message={shares.error.message} onRetry={shares.reload} />;
  if (!shares.data) return <LoadingState label="Loading shared records…" />;
  if (shares.data.items.length === 0) {
    return (
      <div className="rounded-3xl border border-card-border/80 bg-white shadow-soft">
        <EmptyState icon="folder_shared" title="Nothing shared">{empty}</EmptyState>
      </div>
    );
  }

  return (
    <ul className="flex flex-col gap-4">
      {shares.data.items.map((share) => (
        <li key={share.share_id} data-testid="share-card" className="flex flex-col gap-3 rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
          <div className="flex flex-col justify-between gap-1 sm:flex-row sm:items-center">
            <div className="flex items-center gap-2 text-sm font-bold text-slate-800">
              <Icon name="folder_shared" className="text-[18px] text-pine-green" />
              {showPatient ? (
                share.patient ? (
                  <Link href={`/patients/${share.patient.id}`} className="text-primary hover:underline">
                    {share.patient.full_name} ({share.patient.mrn})
                  </Link>
                ) : (
                  <span>
                    {share.patient_name ?? "A patient"} {share.dedan_id ? `(Endod ${share.dedan_id}, not registered here)` : ""}
                  </span>
                )
              ) : (
                <span>Shared by the patient</span>
              )}
            </div>
            <span className="text-[11px] text-slate-500">
              Received {formatDateTime(share.received_at, timeZone)}
              {share.expires_at ? ` • until ${formatDateTime(share.expires_at, timeZone)}` : " • no end date"}
            </span>
          </div>
          <ul className="flex flex-col gap-2">
            {share.records.map((r) => (
              <li key={r.id} data-testid="shared-record" className="flex flex-col gap-2 rounded-2xl border border-slate-100 px-4 py-3">
                <div className="flex items-start gap-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-sky-50 text-sky-700">
                    <Icon name={CATEGORY_ICONS[r.category] ?? "description"} className="text-[16px]" />
                  </div>
                  <div className="flex flex-col">
                    <span className="text-sm font-semibold text-slate-800">{r.title}</span>
                    <span className="text-[11px] text-slate-500">
                      {CATEGORY_LABELS[r.category] ?? r.category} • {formatDateTime(r.occurred_at, timeZone)} • from{" "}
                      <strong>{r.origin}</strong>
                      {r.recorded_by ? ` • ${r.recorded_by}` : ""}
                    </span>
                  </div>
                </div>
                <RecordDetails details={r.details} />
                <FileLinks
                  files={r.files.map((f) => ({ id: f.file_id, filename: f.filename, size: f.size, content_type: f.content_type }))}
                  base={`shared/${share.share_id}/files`}
                />
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}
