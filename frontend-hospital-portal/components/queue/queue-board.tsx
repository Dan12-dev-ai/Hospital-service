"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/ui/icon";
import {
  EmptyState,
  ErrorState,
  FormError,
  LoadingState,
  Modal,
  RoleGate,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { useSignedIn } from "@/components/session/session-context";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import type { BookingList, Hospital, PatientList, Staff } from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import { QUEUE_DESK, type DoctorQueue, type QueueBoard, type QueueEntry, type QueueStatus } from "@/lib/history-types";

/** How often the board refreshes itself. */
const REFRESH_MS = 10_000;

const STATUS_STYLES: Record<QueueStatus, string> = {
  waiting: "bg-slate-100 text-slate-700",
  called: "bg-emerald-100 text-emerald-800",
  done: "bg-sky-50 text-sky-800",
  skipped: "bg-amber-50 text-amber-800",
  cancelled: "bg-rose-50 text-rose-700",
};

export function QueueBoardPage() {
  return (
    <RoleGate roles={[...QUEUE_DESK, "doctor"]} what="the queues">
      <Loaded />
    </RoleGate>
  );
}

function Loaded() {
  const signedIn = useSignedIn();
  if (!signedIn) return null;
  return <Board staff={signedIn.staff} hospital={signedIn.hospital} />;
}

function Board({ staff, hospital }: { staff: Staff; hospital: Hospital }) {
  const { showToast } = useDashboard();
  const board = useApi<QueueBoard>("queue");
  const desk = QUEUE_DESK.includes(staff.role);
  const [checkingIn, setCheckingIn] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const { reload } = board;

  // Auto-refresh, paused while a dialog is open or the tab is hidden.
  useEffect(() => {
    if (checkingIn) return;
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") reload();
    }, REFRESH_MS);
    return () => clearInterval(timer);
  }, [checkingIn, reload]);

  async function act(key: string, path: string, done: string) {
    setBusy(key);
    try {
      await apiFetch(path, { method: "POST" });
      showToast(done);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Could not update the queue.");
    } finally {
      setBusy(null);
      reload();
    }
  }

  if (board.error && !board.data) return <ErrorState message={board.error.message} onRetry={reload} />;
  if (!board.data) return <LoadingState label="Loading queues…" />;
  const data = board.data;

  return (
    <div className="flex w-full flex-col gap-5">
      <header className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-outline">Today</p>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">{desk ? "Queues" : "My queue"}</h1>
          <p className="mt-0.5 text-xs text-slate-500">
            One queue per doctor per day. Patients linked to Endod follow their place in the app;
            {data.notify_ahead > 0
              ? ` anyone with a phone gets an SMS when ${data.notify_ahead} ${data.notify_ahead === 1 ? "person is" : "people are"} ahead, and when called.`
              : " anyone with a phone gets an SMS when called."}
          </p>
        </div>
        {desk && (
          <button type="button" onClick={() => setCheckingIn(true)} className={`${primaryButtonClass} py-2.5`}>
            <Icon name="how_to_reg" className="text-[18px]" />
            Check in
          </button>
        )}
      </header>

      {data.queues.length === 0 ? (
        <div className="rounded-3xl bg-white shadow-soft">
          <EmptyState icon="stethoscope" title="No active doctors">Add doctors to run queues.</EmptyState>
        </div>
      ) : (
        <div className={`grid grid-cols-1 gap-4 ${desk ? "lg:grid-cols-2" : ""}`}>
          {data.queues.map((q) => (
            <QueueCard key={q.doctor.id} queue={q} timeZone={hospital.timezone} busy={busy} onAct={act} />
          ))}
        </div>
      )}

      {checkingIn && (
        <CheckInModal
          board={data}
          hospital={hospital}
          onClose={() => setCheckingIn(false)}
          onDone={(ticket, doctor) => {
            setCheckingIn(false);
            showToast(`Ticket ${ticket} for ${doctor}`);
            reload();
          }}
        />
      )}
    </div>
  );
}

function QueueCard({
  queue,
  timeZone,
  busy,
  onAct,
}: {
  queue: DoctorQueue;
  timeZone: string;
  busy: string | null;
  onAct: (key: string, path: string, done: string) => void;
}) {
  const [showFinished, setShowFinished] = useState(false);
  const open = queue.entries.filter((e) => e.status === "waiting" || e.status === "called");
  const finished = queue.entries.filter((e) => e.status !== "waiting" && e.status !== "called");
  // Yesterday's patients still open (older responses may lack the field).
  const leftovers = queue.leftovers ?? [];

  return (
    <section data-testid="queue-card" className="flex flex-col gap-3 rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-bold text-slate-800">{queue.doctor.full_name}</h2>
          <p className="text-[11px] text-slate-500">
            {queue.waiting} waiting{queue.called ? ` • now seeing ticket ${queue.called.ticket}` : ""}
          </p>
        </div>
        <button
          type="button"
          disabled={busy !== null || queue.waiting === 0 || queue.called !== null}
          title={queue.called ? "Mark the current patient done or skipped first." : undefined}
          onClick={() => onAct(`next-${queue.doctor.id}`, `queue/${queue.doctor.id}/call-next`, "Next patient called")}
          className={primaryButtonClass}
        >
          <Icon name="campaign" className="text-[16px]" />
          Call next
        </button>
      </div>
      {leftovers.length > 0 && (
        <div data-testid="queue-leftovers" className="flex flex-col gap-2 rounded-2xl bg-amber-50/60 p-3">
          <p className="text-[11px] font-semibold text-amber-900">
            From yesterday: {leftovers.length} still open. They are called first,
            and cancelled automatically at noon if still waiting.
          </p>
          <ul className="flex flex-col gap-2">
            {leftovers.map((e) => (
              <EntryRow key={e.id} entry={e} timeZone={timeZone} busy={busy} onAct={onAct} />
            ))}
          </ul>
        </div>
      )}
      {open.length === 0 ? (
        <p className="rounded-xl bg-slate-50 px-3 py-3 text-center text-xs text-slate-500">
          {leftovers.length > 0 ? "Nobody waiting from today." : "Nobody waiting."}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {open.map((e) => (
            <EntryRow key={e.id} entry={e} timeZone={timeZone} busy={busy} onAct={onAct} />
          ))}
        </ul>
      )}
      {finished.length > 0 && (
        <button type="button" onClick={() => setShowFinished((v) => !v)} className="self-start text-[11px] font-semibold text-primary hover:underline">
          {showFinished ? "Hide" : "Show"} {finished.length} finished
        </button>
      )}
      {showFinished && (
        <ul className="flex flex-col gap-2">
          {finished.map((e) => (
            <EntryRow key={e.id} entry={e} timeZone={timeZone} busy={busy} onAct={onAct} />
          ))}
        </ul>
      )}
    </section>
  );
}

function EntryRow({
  entry,
  timeZone,
  busy,
  onAct,
}: {
  entry: QueueEntry;
  timeZone: string;
  busy: string | null;
  onAct: (key: string, path: string, done: string) => void;
}) {
  const action = (name: "done" | "skip" | "cancel", label: string, done: string) => (
    <button
      type="button"
      disabled={busy !== null}
      onClick={() => onAct(`${entry.id}-${name}`, `queue/entries/${entry.id}/${name}`, done)}
      className={secondaryButtonClass}
    >
      {label}
    </button>
  );
  return (
    <li data-testid="queue-entry" className="flex flex-col justify-between gap-2 rounded-2xl border border-slate-100 px-3 py-2 sm:flex-row sm:items-center">
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface-container text-sm font-bold text-primary">
          {entry.ticket}
        </span>
        <div className="flex flex-col">
          <span className="text-sm font-semibold text-slate-800">{entry.patient_name}</span>
          <span className="text-[11px] text-slate-500">
            Checked in {formatDateTime(entry.checked_in_at, timeZone)}
            {entry.status === "waiting" ? ` • ${entry.ahead} ahead` : ""}
            {entry.dedan_id ? " • Endod" : entry.phone ? " • SMS" : ""}
          </span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${STATUS_STYLES[entry.status]}`}>{entry.status}</span>
        {entry.status === "called" && action("done", "Done", `Ticket ${entry.ticket} done`)}
        {(entry.status === "waiting" || entry.status === "called") && action("skip", "Skip", `Ticket ${entry.ticket} skipped`)}
        {(entry.status === "waiting" || entry.status === "called") && action("cancel", "Cancel", `Ticket ${entry.ticket} cancelled`)}
      </div>
    </li>
  );
}

type Way = "booking" | "patient" | "walk_in";

function CheckInModal({
  board,
  hospital,
  onClose,
  onDone,
}: {
  board: QueueBoard;
  hospital: Hospital;
  onClose: () => void;
  onDone: (ticket: number, doctor: string) => void;
}) {
  const [way, setWay] = useState<Way>("booking");
  const [doctorId, setDoctorId] = useState(board.queues[0]?.doctor.id ?? "");
  const [bookingId, setBookingId] = useState("");
  const [query, setQuery] = useState("");
  const [patientId, setPatientId] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const bookings = useApi<BookingList>(
    way === "booking" ? `bookings?status=confirmed&mode=in_person&day=${board.today}` : null
  );
  const search = query.trim();
  const patients = useApi<PatientList>(
    way !== "walk_in" && search.length >= 2 ? `patients?limit=8&q=${encodeURIComponent(search)}` : null
  );
  const booking = bookings.data?.items.find((b) => b.id === bookingId) ?? null;

  async function submit() {
    let body: Record<string, unknown>;
    if (way === "booking") {
      if (!booking) return setError("Choose the booking.");
      body = { booking_id: booking.id, doctor_id: booking.doctor?.id ?? (doctorId || null), patient_id: patientId || null };
    } else if (way === "patient") {
      if (!patientId) return setError("Find and choose the patient.");
      if (!doctorId) return setError("Choose the doctor.");
      body = { patient_id: patientId, doctor_id: doctorId };
    } else {
      if (name.trim().length < 2) return setError("Enter the patient's name.");
      if (!phone.trim()) return setError("Enter a phone number for the SMS.");
      if (!doctorId) return setError("Choose the doctor.");
      body = { doctor_id: doctorId, walk_in: { name: name.trim(), phone: phone.trim() } };
    }
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<DoctorQueue & { ticket: number }>("queue/check-in", { method: "POST", body });
      onDone(result.ticket, result.doctor.full_name);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not check the patient in.");
      setBusy(false);
    }
  }

  const tabs: { key: Way; label: string }[] = [
    { key: "booking", label: "Endod booking" },
    { key: "patient", label: "Registered patient" },
    { key: "walk_in", label: "Walk-in" },
  ];

  return (
    <Modal
      title="Check in"
      icon="how_to_reg"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButtonClass}>Cancel</button>
          <button type="button" disabled={busy} onClick={submit} className={primaryButtonClass}>
            {busy ? "Checking in…" : "Check in"}
          </button>
        </>
      }
    >
      <div role="tablist" className="flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={way === t.key}
            onClick={() => { setWay(t.key); setError(null); }}
            className={way === t.key ? primaryButtonClass : secondaryButtonClass}>
            {t.label}
          </button>
        ))}
      </div>

      {way === "booking" && (
        <div>
          <label htmlFor="checkin-booking" className={labelClass}>Today&apos;s confirmed in-person bookings</label>
          {bookings.error ? (
            <FormError message={bookings.error.message} />
          ) : (
            <select id="checkin-booking" value={bookingId} onChange={(e) => setBookingId(e.target.value)} className={inputClass}>
              <option value="">{bookings.loading ? "Loading…" : (bookings.data?.items.length ?? 0) === 0 ? "No bookings today" : "Choose a booking"}</option>
              {(bookings.data?.items ?? []).map((b) => (
                <option key={b.id} value={b.id}>
                  {formatDateTime(b.scheduled_at, hospital.timezone)} • {b.patient.name}
                  {b.doctor ? ` • ${b.doctor.full_name}` : ""}
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      {way !== "walk_in" && (
        <div className="flex flex-col gap-2">
          <label htmlFor="checkin-search" className={labelClass}>
            {way === "booking" ? "Their hospital record (optional; it is linked to Endod)" : "Find the patient (name, MRN or phone)"}
          </label>
          <input id="checkin-search" value={query} onChange={(e) => { setQuery(e.target.value); setPatientId(""); }} className={inputClass} />
          {(patients.data?.items ?? []).length > 0 && (
            <ul className="flex flex-col gap-1">
              {patients.data!.items.map((p) => (
                <li key={p.id}>
                  <label className={`flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-xs ${patientId === p.id ? "bg-pine-light" : "bg-surface-container-low"}`}>
                    <input type="radio" name="checkin-patient" checked={patientId === p.id} onChange={() => setPatientId(p.id)} />
                    <span className="font-semibold">{p.full_name}</span>
                    <span className="text-slate-500">{p.mrn}{p.dedan_id ? ` • Endod ${p.dedan_id}` : ""}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {way === "walk_in" && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="checkin-name" className={labelClass}>Name</label>
            <input id="checkin-name" maxLength={160} value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
          </div>
          <div>
            <label htmlFor="checkin-phone" className={labelClass}>Phone (for the SMS)</label>
            <input id="checkin-phone" type="tel" placeholder="0911 234 567" value={phone} onChange={(e) => setPhone(e.target.value)} className={inputClass} />
          </div>
        </div>
      )}

      {(way !== "booking" || (booking !== null && booking.doctor === null)) && (
        <div>
          <label htmlFor="checkin-doctor" className={labelClass}>Doctor</label>
          <select id="checkin-doctor" value={doctorId} onChange={(e) => setDoctorId(e.target.value)} className={inputClass}>
            {board.queues.map((q) => (
              <option key={q.doctor.id} value={q.doctor.id}>{q.doctor.full_name} ({q.waiting} waiting)</option>
            ))}
          </select>
        </div>
      )}
      <FormError message={error} />
    </Modal>
  );
}
