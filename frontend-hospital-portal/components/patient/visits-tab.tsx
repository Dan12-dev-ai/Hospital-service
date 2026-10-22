"use client";

import { useState } from "react";
import { Icon } from "@/components/ui/icon";
import {
  EmptyState,
  ErrorState,
  FormError,
  LoadingState,
  Modal,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import type { DoctorList, Hospital, Staff } from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import { FOLLOW_UP_SETTERS, RECORD_WRITERS, type Visit } from "@/lib/history-types";

/** "YYYY-MM-DD" for today in the hospital's time zone, shifted by `days`. */
export function hospitalDay(timeZone: string, days = 0): string {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  const [y, m, d] = today.split("-").map(Number);
  const shifted = new Date(Date.UTC(y, m - 1, d + days));
  return shifted.toISOString().slice(0, 10);
}

function formatDay(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(y, m - 1, d)));
}

/** A patient's visits, each with its follow-up (sent to the Endod app when the patient is linked). */
export function VisitsTab({ patientId, staff, hospital }: { patientId: string; staff: Staff; hospital: Hospital }) {
  const { showToast } = useDashboard();
  const visits = useApi<Visit[]>(`patients/${patientId}/visits`);
  const [opening, setOpening] = useState(false);
  const [editing, setEditing] = useState<Visit | null>(null);
  const canOpen = RECORD_WRITERS.includes(staff.role);
  const canFollowUp = FOLLOW_UP_SETTERS.includes(staff.role);

  async function cancelFollowUp(visit: Visit) {
    try {
      await apiFetch(`visits/${visit.id}`, { method: "PATCH", body: { follow_up_on: null } });
      showToast("Follow-up cancelled");
      visits.reload();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Could not cancel the follow-up.");
    }
  }

  if (visits.error) return <ErrorState message={visits.error.message} onRetry={visits.reload} />;
  if (!visits.data) return <LoadingState label="Loading visits…" />;

  return (
    <div className="flex flex-col gap-4 rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-slate-500">
          A visit groups the records written during it. A doctor may set a follow-up: the patient gets a reminder in
          the Endod app and by SMS the day before.
        </p>
        {canOpen && (
          <button type="button" onClick={() => setOpening(true)} className={primaryButtonClass}>
            <Icon name="add" className="text-[16px]" />
            Open visit
          </button>
        )}
      </div>
      {visits.data.length === 0 ? (
        <EmptyState icon="event_repeat" title="No visits yet" />
      ) : (
        <ul className="flex flex-col gap-2">
          {visits.data.map((v) => (
            <li key={v.id} data-testid="visit-row"
              className="flex flex-col justify-between gap-2 rounded-2xl border border-slate-100 px-4 py-3 sm:flex-row sm:items-center">
              <div className="flex flex-col">
                <span className="text-sm font-semibold text-slate-800">{formatDateTime(v.started_at, hospital.timezone)}</span>
                <span className="text-[11px] text-slate-500">{v.doctor?.full_name ?? "No doctor named"}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {v.follow_up_on ? (
                  <span data-testid="follow-up" className="rounded-full bg-sky-50 px-2.5 py-1 text-[11px] font-semibold text-sky-900">
                    Follow-up {formatDay(v.follow_up_on)}
                    {v.follow_up_note ? `: ${v.follow_up_note}` : ""}
                    {v.follow_up_sent ? " • sent to Endod" : ""}
                  </span>
                ) : (
                  <span className="text-[11px] text-slate-400">No follow-up</span>
                )}
                {canFollowUp && (
                  <>
                    <button type="button" onClick={() => setEditing(v)} className={secondaryButtonClass}>
                      {v.follow_up_on ? "Change follow-up" : "Set follow-up"}
                    </button>
                    {v.follow_up_on && (
                      <button type="button" onClick={() => cancelFollowUp(v)} className={secondaryButtonClass}>
                        Cancel follow-up
                      </button>
                    )}
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {opening && (
        <VisitModal
          patientId={patientId}
          staff={staff}
          hospital={hospital}
          onClose={() => setOpening(false)}
          onSaved={() => {
            setOpening(false);
            showToast("Visit opened");
            visits.reload();
          }}
        />
      )}
      {editing && (
        <VisitModal
          patientId={patientId}
          staff={staff}
          hospital={hospital}
          visit={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            showToast("Follow-up saved");
            visits.reload();
          }}
        />
      )}
    </div>
  );
}

/** Opens a visit (with an optional follow-up), or sets the follow-up of `visit`. */
function VisitModal({
  patientId,
  staff,
  hospital,
  visit,
  onClose,
  onSaved,
}: {
  patientId: string;
  staff: Staff;
  hospital: Hospital;
  visit?: Visit;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isDoctor = staff.role === "doctor";
  const doctors = useApi<DoctorList>(!visit && !isDoctor ? "doctors" : null);
  const [doctorId, setDoctorId] = useState("");
  const [followUp, setFollowUp] = useState(visit?.follow_up_on ?? "");
  const [note, setNote] = useState(visit?.follow_up_note ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canFollowUp = FOLLOW_UP_SETTERS.includes(staff.role);
  const min = hospitalDay(hospital.timezone, 1);

  async function save() {
    if (visit && !followUp) {
      setError("Choose the follow-up date.");
      return;
    }
    if (followUp && followUp < min) {
      setError("The follow-up must be after today.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (visit) {
        await apiFetch(`visits/${visit.id}`, { method: "PATCH", body: { follow_up_on: followUp, follow_up_note: note.trim() || null } });
      } else {
        await apiFetch(`patients/${patientId}/visits`, {
          method: "POST",
          body: {
            doctor_id: doctorId || null,
            follow_up_on: followUp || null,
            follow_up_note: followUp ? note.trim() || null : null,
          },
        });
      }
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
      setBusy(false);
    }
  }

  return (
    <Modal
      title={visit ? "Follow-up" : "Open visit"}
      icon="event_repeat"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButtonClass}>Cancel</button>
          <button type="button" disabled={busy} onClick={save} className={primaryButtonClass}>
            {busy ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-3">
        {!visit && !isDoctor && (
          <div>
            <label htmlFor="visit-doctor" className={labelClass}>Doctor (optional)</label>
            <select id="visit-doctor" value={doctorId} onChange={(e) => setDoctorId(e.target.value)} className={inputClass}>
              <option value="">No doctor</option>
              {(doctors.data?.items ?? []).filter((d) => d.active).map((d) => (
                <option key={d.id} value={d.id}>{d.full_name}</option>
              ))}
            </select>
          </div>
        )}
        {canFollowUp ? (
          <>
            <div>
              <label htmlFor="visit-follow-up" className={labelClass}>Follow-up date{visit ? "" : " (optional)"}</label>
              <input id="visit-follow-up" type="date" min={min} max={hospitalDay(hospital.timezone, 730)} value={followUp}
                onChange={(e) => setFollowUp(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label htmlFor="visit-note" className={labelClass}>Note for the patient (optional)</label>
              <input id="visit-note" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} className={inputClass} />
            </div>
          </>
        ) : (
          <p className="text-xs text-slate-500">A doctor sets follow-ups.</p>
        )}
      </div>
      <FormError message={error} />
    </Modal>
  );
}
