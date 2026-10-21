"use client";

import { useMemo, useState, type FormEvent } from "react";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { ErrorState, LoadingState, RoleGate, FormError, inputClass, labelClass, primaryButtonClass } from "@/components/common/states";
import { useSignedIn } from "@/components/session/session-context";
import { useApi } from "@/lib/api";
import type { Booking, BookingList, Hospital, Staff } from "@/lib/api-types";

type FollowUp = {
  id: string;
  patientName: string;
  returnDate: string;
  reason: string;
  createdAt: string;
};

export function FollowUpPage() {
  return (
    <RoleGate roles="any" what="patient follow-up">
      <FollowUpLoaded />
    </RoleGate>
  );
}

function FollowUpLoaded() {
  const signedIn = useSignedIn();
  if (!signedIn) return null;
  return <FollowUp staff={signedIn.staff} hospital={signedIn.hospital} />;
}

function FollowUp({ hospital }: { staff: Staff; hospital: Hospital }) {
  const { showToast } = useDashboard();
  const list = useApi<BookingList>("bookings?status=confirmed");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [returnDate, setReturnDate] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<FollowUp[]>([]);

  const approvedToday = useMemo(() => {
    const today = new Date().toDateString();
    return (list.data?.items ?? []).filter(
      (booking) => new Date(booking.scheduled_at).toDateString() === today
    );
  }, [list.data]);

  const selected = approvedToday.find((b) => b.id === selectedId) ?? null;

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!selected) {
      setError("Select a patient from today's approved appointments.");
      return;
    }
    if (!returnDate) {
      setError("Choose the date to return.");
      return;
    }
    const entry: FollowUp = {
      id: `${Date.now()}`,
      patientName: selected.patient.name,
      returnDate,
      reason: reason.trim(),
      createdAt: new Date().toISOString(),
    };
    setItems((current) => [entry, ...current]);
    showToast(`Follow-up scheduled for ${entry.patientName} on ${entry.returnDate}.`);
    setReturnDate("");
    setReason("");
    setError(null);
  }

  return (
    <div className="flex w-full flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Patient follow-up</h1>
        <p className="text-xs text-slate-500">
          Select a patient with an approved appointment today, then schedule their return date.
        </p>
      </div>

      {list.error ? (
        <ErrorState message={list.error.message} onRetry={list.reload} />
      ) : !list.data ? (
        <LoadingState label="Loading approved appointments…" />
      ) : (
        <>
          <div className="rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
            <h2 className="mb-3 text-sm font-bold text-slate-800">Approved appointments today</h2>
            {approvedToday.length === 0 ? (
              <p className="text-xs text-slate-500">No approved appointments for today.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {approvedToday.map((booking) => (
                  <li key={booking.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(booking.id)}
                      className={`flex w-full items-center justify-between gap-3 rounded-2xl px-4 py-2.5 text-xs transition-colors ${
                        selectedId === booking.id
                          ? "bg-pine-green text-white"
                          : "bg-slate-50 text-slate-800 hover:bg-slate-100"
                      }`}
                    >
                      <span className="font-semibold">{booking.patient.name}</span>
                      <span className="opacity-80">
                        {new Date(booking.scheduled_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <form onSubmit={handleSubmit} className="flex w-full flex-col gap-4 rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label htmlFor="followup-patient" className={labelClass}>Selected patient</label>
                <input id="followup-patient" type="text" value={selected ? selected.patient.name : ""} readOnly placeholder="Select a patient above" className={inputClass} />
              </div>
              <div>
                <label htmlFor="followup-date" className={labelClass}>Return date</label>
                <input id="followup-date" type="date" value={returnDate} onChange={(e) => setReturnDate(e.target.value)} className={inputClass} />
              </div>
              <div className="sm:col-span-2">
                <label htmlFor="followup-reason" className={labelClass}>Reason (optional)</label>
                <textarea id="followup-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Review lab results" rows={3} className={inputClass} />
              </div>
            </div>
            <FormError message={error} />
            <div className="flex justify-end">
              <button type="submit" className={primaryButtonClass}>
                <Icon name="event_repeat" className="text-[16px]" />
                Schedule follow-up
              </button>
            </div>
          </form>

          {items.length > 0 && (
            <div className="rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
              <h2 className="mb-3 text-sm font-bold text-slate-800">Scheduled follow-ups</h2>
              <ul className="flex flex-col gap-2">
                {items.map((item) => (
                  <li key={item.id} className="flex items-center justify-between gap-3 rounded-2xl bg-slate-50 px-4 py-2.5 text-xs">
                    <span className="font-semibold text-slate-800">{item.patientName}</span>
                    <span className="text-slate-500">{item.returnDate}</span>
                    {item.reason && <span className="text-slate-400">{item.reason}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
