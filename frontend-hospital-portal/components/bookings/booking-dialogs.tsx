"use client";

import { useState } from "react";
import {
  FormError,
  Modal,
  dangerButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { useApi } from "@/lib/api";
import type { Booking, DoctorList } from "@/lib/api-types";

export type ReasonAction = "reject" | "cancel";

/** Reject (not yet approved) or cancel (confirmed): the patient is refunded, so a reason is required. */
export function ReasonDialog({
  action,
  booking,
  onClose,
  onConfirm,
}: {
  action: ReasonAction;
  booking: Booking;
  onClose: () => void;
  /** Resolves to an error message, or null when done. */
  onConfirm: (reason: string) => Promise<string | null>;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const verb = action === "reject" ? "Reject" : "Cancel";

  async function submit() {
    if (reason.trim().length < 2) {
      setError("Give the patient a reason (at least 2 characters).");
      return;
    }
    setBusy(true);
    setError(await onConfirm(reason.trim()));
    setBusy(false);
  }

  return (
    <Modal
      title={`${verb} booking`}
      icon={action === "reject" ? "block" : "event_busy"}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButtonClass}>
            Keep booking
          </button>
          <button type="button" disabled={busy} onClick={submit} className={dangerButtonClass}>
            {busy ? "Saving…" : `${verb} booking`}
          </button>
        </>
      }
    >
      <p className="text-xs text-slate-600">
        {booking.patient.name} ({booking.patient.dedan_id}) paid through Endod and will be refunded. The reason is sent
        to the patient.
      </p>
      <div>
        <label htmlFor="booking-reason" className={labelClass}>
          Reason
        </label>
        <textarea
          id="booking-reason"
          rows={3}
          maxLength={300}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className={inputClass}
        />
      </div>
      <FormError message={error} />
    </Modal>
  );
}

/** An admin approves a video visit on behalf of a doctor, who becomes the visit's doctor. */
export function ApproveDialog({
  booking,
  onClose,
  onConfirm,
}: {
  booking: Booking;
  onClose: () => void;
  onConfirm: (doctorId: string) => Promise<string | null>;
}) {
  const doctors = useApi<DoctorList>("doctors");
  const [doctorId, setDoctorId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!doctorId) {
      setError("Choose the doctor for this visit.");
      return;
    }
    setBusy(true);
    setError(await onConfirm(doctorId));
    setBusy(false);
  }

  const items = doctors.data?.items ?? [];
  return (
    <Modal
      title="Approve video visit"
      icon="video_call"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButtonClass}>
            Close
          </button>
          <button type="button" disabled={busy || !doctorId} onClick={submit} className={primaryButtonClass}>
            {busy ? "Approving…" : "Approve"}
          </button>
        </>
      }
    >
      <p className="text-xs text-slate-600">
        Choose the doctor who will see {booking.patient.name}. The doctor runs the call.
      </p>
      <div>
        <label htmlFor="approve-doctor" className={labelClass}>
          Doctor
        </label>
        {doctors.error ? (
          <FormError message={doctors.error.message} />
        ) : doctors.loading && !doctors.data ? (
          <p className="text-xs text-slate-500">Loading doctors…</p>
        ) : items.length === 0 ? (
          <p className="text-xs text-slate-500">No active doctors yet. Add a doctor on the Doctors page first.</p>
        ) : (
          <select id="approve-doctor" value={doctorId} onChange={(event) => setDoctorId(event.target.value)} className={inputClass}>
            <option value="">Choose a doctor…</option>
            {items.map((doctor) => (
              <option key={doctor.id} value={doctor.id}>
                {doctor.full_name}
                {doctor.specialty ? ` — ${doctor.specialty}` : ""}
              </option>
            ))}
          </select>
        )}
      </div>
      <FormError message={error} />
    </Modal>
  );
}
