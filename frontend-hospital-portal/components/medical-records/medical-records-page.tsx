"use client";

import { useMemo, useState, type FormEvent } from "react";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { ErrorState, LoadingState, RoleGate, FormError, inputClass, labelClass, primaryButtonClass } from "@/components/common/states";
import { useSignedIn } from "@/components/session/session-context";
import { useApi } from "@/lib/api";
import type { BookingList } from "@/lib/api-types";

type MedicalRecord = {
  id: string;
  patientName: string;
  disease: string;
  medicine: string;
  notes: string;
  createdAt: string;
};

export function MedicalRecordsPage() {
  return (
    <RoleGate roles={["doctor", "admin", "nurse", "records"]} what="medical records">
      <MedicalRecordsLoaded />
    </RoleGate>
  );
}

function MedicalRecordsLoaded() {
  const signedIn = useSignedIn();
  if (!signedIn) return null;
  return <MedicalRecords />;
}

function MedicalRecords() {
  const { showToast } = useDashboard();
  const list = useApi<BookingList>("bookings?status=confirmed");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [disease, setDisease] = useState("");
  const [medicine, setMedicine] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [records, setRecords] = useState<MedicalRecord[]>([]);

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
    if (disease.trim().length < 2) {
      setError("Enter the disease or diagnosis.");
      return;
    }
    if (medicine.trim().length < 2) {
      setError("Enter the medicine ordered.");
      return;
    }
    const entry: MedicalRecord = {
      id: `${Date.now()}`,
      patientName: selected.patient.name,
      disease: disease.trim(),
      medicine: medicine.trim(),
      notes: notes.trim(),
      createdAt: new Date().toISOString(),
    };
    setRecords((current) => [entry, ...current]);
    showToast(`Medical record saved for ${entry.patientName}.`);
    setDisease("");
    setMedicine("");
    setNotes("");
    setError(null);
  }

  return (
    <div className="flex w-full flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Medical records</h1>
        <p className="text-xs text-slate-500">
          Select a patient with an approved appointment today, then add their diagnosis and prescribed medicine.
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
                          ? "bg-black text-white"
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
                <label htmlFor="mr-patient" className={labelClass}>Selected patient</label>
                <input id="mr-patient" type="text" value={selected ? selected.patient.name : ""} readOnly placeholder="Select a patient above" className={inputClass} />
              </div>
              <div>
                <label htmlFor="mr-disease" className={labelClass}>Disease / diagnosis</label>
                <input id="mr-disease" type="text" value={disease} onChange={(e) => setDisease(e.target.value)} placeholder="e.g. Malaria" className={inputClass} />
              </div>
              <div>
                <label htmlFor="mr-medicine" className={labelClass}>Medicine ordered</label>
                <input id="mr-medicine" type="text" value={medicine} onChange={(e) => setMedicine(e.target.value)} placeholder="e.g. Artemether-Lumefantrine" className={inputClass} />
              </div>
              <div className="sm:col-span-2">
                <label htmlFor="mr-notes" className={labelClass}>Notes (optional)</label>
                <textarea id="mr-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className={inputClass} />
              </div>
            </div>
            <FormError message={error} />
            <div className="flex justify-end">
              <button type="submit" className={primaryButtonClass}>
                <Icon name="save" className="text-[16px]" />
                Save medical record
              </button>
            </div>
          </form>

          {records.length > 0 && (
            <div className="rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
              <h2 className="mb-3 text-sm font-bold text-slate-800">Saved records</h2>
              <ul className="flex flex-col gap-2">
                {records.map((record) => (
                  <li key={record.id} className="rounded-2xl bg-slate-50 px-4 py-2.5 text-xs">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-semibold text-slate-800">{record.patientName}</span>
                      <span className="text-slate-500">{record.disease}</span>
                    </div>
                    <p className="text-slate-400">{record.medicine}</p>
                    {record.notes && <p className="text-slate-400">{record.notes}</p>}
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
