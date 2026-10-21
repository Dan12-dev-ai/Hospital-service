"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Icon } from "@/components/ui/icon";
import { ErrorState, LoadingState, RoleGate } from "@/components/common/states";
import { useSignedIn } from "@/components/session/session-context";
import { EndodLink } from "@/components/patient/endod-link";
import { RecordsTab } from "@/components/patient/records-tab";
import { VisitsTab } from "@/components/patient/visits-tab";
import { SharedList } from "@/components/patient/shared-list";
import { useApi } from "@/lib/api";
import type { ApiPatient, Hospital, Staff } from "@/lib/api-types";
import { LINKERS, RECORD_READERS } from "@/lib/history-types";
import { STATUS_LABELS } from "@/lib/patient-types";

type FullPatient = ApiPatient & { phone?: string | null; date_of_birth?: string | null };

const TABS = [
  { key: "records", label: "Records", icon: "folder_open" },
  { key: "visits", label: "Visits and follow-ups", icon: "event_repeat" },
  { key: "shared", label: "Shared with us", icon: "folder_shared" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

/** Ids are 32 lowercase hex characters; anything else never reaches the API. */
export const ID_PATTERN = /^[0-9a-f]{32}$/;

export function PatientChart() {
  return (
    <RoleGate roles="any" what="patients">
      <ChartLoaded />
    </RoleGate>
  );
}

function ChartLoaded() {
  const signedIn = useSignedIn();
  const params = useParams<{ id: string }>();
  const id = typeof params.id === "string" && ID_PATTERN.test(params.id) ? params.id : null;
  if (!signedIn) return null;
  if (!id) return <ErrorState message="Patient not found." />;
  return <Chart id={id} staff={signedIn.staff} hospital={signedIn.hospital} />;
}

function Chart({ id, staff, hospital }: { id: string; staff: Staff; hospital: Hospital }) {
  const patient = useApi<FullPatient>(`patients/${id}`);
  const [tab, setTab] = useState<TabKey>("records");
  const reader = RECORD_READERS.includes(staff.role);

  if (patient.error) return <ErrorState message={patient.error.message} onRetry={patient.reload} />;
  if (!patient.data) return <LoadingState label="Loading the patient…" />;
  const p = patient.data;

  return (
    <div className="flex w-full flex-col gap-5">
      <header className="flex flex-col gap-2">
        <Link href="/patients" className="flex items-center gap-1 text-xs font-semibold text-primary hover:underline">
          <Icon name="arrow_back" className="text-[16px]" />
          Patients
        </Link>
        <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-end">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900" data-testid="patient-name">
              {p.full_name}
              {p.full_name_am && <span className="ml-2 text-base font-medium text-slate-400">({p.full_name_am})</span>}
            </h1>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
              <span className="font-semibold text-primary">{p.mrn}</span>
              <span>•</span>
              <span>{p.sex === "female" ? "Female" : "Male"}{p.age_years !== null ? `, ${p.age_years} y` : ""}</span>
              <span>•</span>
              <span>{STATUS_LABELS[p.status]}</span>
              {p.dedan_id && (
                <>
                  <span>•</span>
                  <span className="font-semibold text-pine-green">Endod {p.dedan_id}</span>
                </>
              )}
            </p>
          </div>
        </div>
      </header>

      <EndodLink
        patientId={id}
        canLink={LINKERS.includes(staff.role)}
        timeZone={hospital.timezone}
        onChange={patient.reload}
      />

      {reader ? (
        <section className="flex flex-col gap-4">
          <div role="tablist" aria-label="Patient history" className="flex flex-wrap gap-2">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                onClick={() => setTab(t.key)}
                className={`inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-semibold transition-colors ${
                  tab === t.key ? "bg-pine-green text-white shadow-sm" : "bg-white text-slate-600 hover:bg-slate-50"
                }`}
              >
                <Icon name={t.icon} className="text-[16px]" />
                {t.label}
              </button>
            ))}
          </div>
          {tab === "records" && <RecordsTab patientId={id} staff={staff} hospital={hospital} />}
          {tab === "visits" && <VisitsTab patientId={id} staff={staff} hospital={hospital} />}
          {tab === "shared" && (
            <SharedList path={`shared?patient_id=${id}`} timeZone={hospital.timezone} showPatient={false}
              empty={p.dedan_id ? "This patient has not shared records from Endod with this hospital." : "Link the patient to Endod first: patients share records from their Endod app."} />
          )}
        </section>
      ) : (
        <p className="rounded-2xl bg-white px-5 py-4 text-xs text-slate-500 shadow-soft">
          Clinical records are shown to clinical and records staff only.
        </p>
      )}
    </div>
  );
}
