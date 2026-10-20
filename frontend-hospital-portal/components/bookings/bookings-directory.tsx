"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { ErrorState, LoadingState, RoleGate } from "@/components/common/states";
import { useSignedIn } from "@/components/session/session-context";
import { BookingsTable } from "@/components/bookings/bookings-table";
import { ApproveDialog, ReasonDialog, type ReasonAction } from "@/components/bookings/booking-dialogs";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import type { Booking, BookingList, BookingStatus, Hospital, Staff, VisitMode } from "@/lib/api-types";
import { BOOKING_STATUS_LABELS, BOOKING_VIEWERS } from "@/lib/booking-rules";

const STATUS_KEYS: BookingStatus[] = ["awaiting_doctor", "confirmed", "completed", "rejected", "cancelled"];

function isStatus(value: string | null): value is BookingStatus {
  return value !== null && (STATUS_KEYS as string[]).includes(value);
}

export function BookingsDirectory() {
  return (
    <RoleGate roles={BOOKING_VIEWERS} what="Endod bookings">
      <BookingsLoaded />
    </RoleGate>
  );
}

function BookingsLoaded() {
  const signedIn = useSignedIn();
  if (!signedIn) return null;
  return <Bookings staff={signedIn.staff} hospital={signedIn.hospital} />;
}

type Pending =
  | { kind: "approve"; booking: Booking }
  | { kind: ReasonAction; booking: Booking }
  | null;

function Bookings({ staff, hospital }: { staff: Staff; hospital: Hospital }) {
  const params = useSearchParams();
  const initialStatus = params.get("status");
  const { showToast } = useDashboard();
  const searchRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<BookingStatus | "all">(isStatus(initialStatus) ? initialStatus : "all");
  const [mode, setMode] = useState<VisitMode | "all">("all");
  const [mine, setMine] = useState(false);
  const [query, setQuery] = useState("");
  const [pending, setPending] = useState<Pending>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const path = useMemo(() => {
    const search = new URLSearchParams();
    if (status !== "all") search.set("status", status);
    if (mode !== "all") search.set("mode", mode);
    if (mine) search.set("mine", "true");
    const text = search.toString();
    return text ? `bookings?${text}` : "bookings";
  }, [status, mode, mine]);
  const list = useApi<BookingList>(path);
  const { reload } = list;

  // Bookings arrive from the Endod app at any time.
  useEffect(() => {
    const interval = setInterval(reload, 30_000);
    return () => clearInterval(interval);
  }, [reload]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const rows = useMemo(() => {
    const items = list.data?.items ?? [];
    const search = query.trim().toLowerCase();
    if (!search) return items;
    return items.filter((b) =>
      [b.patient.name, b.patient.dedan_id, b.patient.phone ?? "", b.doctor?.full_name ?? "", b.service ?? ""]
        .join(" ")
        .toLowerCase()
        .includes(search)
    );
  }, [list.data, query]);

  const counts = list.data?.counts;
  const total = counts ? Object.values(counts).reduce((sum, n) => sum + n, 0) : 0;

  async function act(booking: Booking, action: "approve" | "reject" | "cancel" | "complete", body: object, done: string) {
    setBusyId(booking.id);
    try {
      await apiFetch<Booking>(`bookings/${booking.id}/${action}`, { method: "POST", body });
      showToast(done);
      setPending(null);
      reload();
      return null;
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "The action failed.";
      // A stale row (someone else already decided): refresh the list.
      if (err instanceof ApiError && err.status === 409) reload();
      return message;
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="flex w-full flex-col">
      {/* Command bar */}
      <div className="mb-space-xl flex flex-col justify-between gap-space-md md:flex-row md:items-end">
        <div className="flex min-w-0 flex-col">
          <div className="mb-1 flex items-center gap-space-xs">
            <span className="h-1.5 w-1.5 rounded-full bg-primary-container" />
            <span className="font-label-sm text-label-sm uppercase tracking-wider text-outline">
              Endod bookings • Paid through the Endod app
            </span>
          </div>
          <h1 className="mb-1 font-headline-xl text-headline-xl leading-none tracking-tight text-on-surface">
            Appointments
            <span className="font-body-md text-headline-lg font-normal text-outline"> — {total} bookings</span>
          </h1>
          <p className="flex items-center gap-1.5 font-body-sm text-body-sm text-outline">
            <Icon name="local_hospital" className="text-[15px] text-primary" />
            <span>
              {hospital.name}
              {hospital.name_am ? ` • ${hospital.name_am}` : ""}
            </span>
          </p>
        </div>
        <button
          type="button"
          onClick={reload}
          className="flex items-center gap-1.5 rounded-xl bg-surface-container-lowest px-space-md py-2.5 font-label-md text-label-md text-on-surface shadow-soft transition-all hover:bg-surface-container-high"
        >
          <Icon name="refresh" className="text-[18px] text-outline" />
          <span>Refresh</span>
        </button>
      </div>

      {/* KPIs */}
      <div className="mb-space-xl grid grid-cols-2 gap-space-md lg:grid-cols-4">
        {[
          { label: "Awaiting approval", value: counts?.awaiting_doctor, icon: "hourglass_top", iconClass: "bg-secondary-container text-on-secondary-container" },
          { label: "Confirmed", value: counts?.confirmed, icon: "event_available", iconClass: "bg-surface-container text-primary" },
          { label: "Completed", value: counts?.completed, icon: "check_circle", iconClass: "bg-surface-container-high text-primary-container" },
          { label: "Rejected / cancelled", value: counts ? counts.rejected + counts.cancelled : undefined, icon: "event_busy", iconClass: "bg-primary-fixed text-on-primary-fixed-variant" },
        ].map((kpi) => (
          <div key={kpi.label} className="flex h-32 flex-col justify-between rounded-2xl bg-surface-container-lowest p-space-lg shadow-soft">
            <div className="flex items-center justify-between">
              <span className="font-label-md text-label-md text-outline">{kpi.label}</span>
              <div className={cn("flex h-8 w-8 items-center justify-center rounded-xl", kpi.iconClass)}>
                <Icon name={kpi.icon} className="text-[18px]" />
              </div>
            </div>
            <div className="font-metric-display text-metric-display tracking-tight text-on-surface">{kpi.value ?? "—"}</div>
          </div>
        ))}
      </div>

      {/* Toolbar */}
      <div className="mb-space-lg flex flex-col gap-space-md rounded-2xl bg-surface-container-lowest p-space-md shadow-soft">
        <div className="flex flex-col items-stretch justify-between gap-space-md lg:flex-row lg:items-center">
          <div className="relative min-w-0 flex-1">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5 text-outline">
              <Icon name="search" className="text-[18px]" />
            </div>
            <input
              ref={searchRef}
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by patient name, Endod ID, phone, doctor..."
              className="w-full rounded-xl bg-surface-container-low py-2.5 pl-10 pr-16 font-body-md text-body-md text-on-surface transition-all placeholder:text-outline focus:bg-surface-container-lowest focus:outline-none focus:ring-2 focus:ring-primary-container"
            />
          </div>
          <div className="flex shrink-0 items-center gap-space-sm">
            {staff.role === "doctor" && (
              <label className="flex cursor-pointer items-center gap-2 rounded-xl bg-surface-container-low px-3 py-2.5 font-label-md text-label-md text-on-surface">
                <input type="checkbox" checked={mine} onChange={(event) => setMine(event.target.checked)} className="h-4 w-4 accent-[#1b6b57]" />
                My visits only
              </label>
            )}
            <div className="relative">
              <select
                aria-label="Visit type"
                value={mode}
                onChange={(event) => setMode(event.target.value as VisitMode | "all")}
                className="cursor-pointer appearance-none rounded-xl bg-surface-container-low py-2.5 pl-3 pr-8 font-label-md text-label-md text-on-surface focus:outline-none"
              >
                <option value="all">All visit types</option>
                <option value="in_person">In person</option>
                <option value="video">Video</option>
              </select>
              <Icon name="expand_more" className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[16px] text-outline" />
            </div>
          </div>
        </div>

        <div role="tablist" aria-label="Booking status" className="flex items-center gap-1.5 overflow-x-auto pb-0.5 pt-1">
          {(["all", ...STATUS_KEYS] as const).map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={status === key}
              data-testid={`status-tab-${key}`}
              onClick={() => setStatus(key)}
              className={cn(
                "shrink-0 rounded-full px-3.5 py-1.5 font-label-md text-label-md transition-all",
                status === key
                  ? "bg-primary-container text-on-primary shadow-xs"
                  : "bg-surface-container-low text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
              )}
            >
              {key === "all" ? "All" : BOOKING_STATUS_LABELS[key]}{" "}
              <span className="ml-1 font-normal opacity-80">{counts ? (key === "all" ? total : counts[key]) : ""}</span>
            </button>
          ))}
        </div>
      </div>

      {list.error ? (
        <ErrorState message={list.error.message} onRetry={reload} />
      ) : !list.data ? (
        <LoadingState label="Loading bookings…" />
      ) : (
        <BookingsTable
          rows={rows}
          staff={staff}
          timeZone={hospital.timezone}
          busyId={busyId}
          filtered={status !== "all" || mode !== "all" || mine || query.trim() !== ""}
          onApprove={(booking) => setPending({ kind: "approve", booking })}
          onReject={(booking) => setPending({ kind: "reject", booking })}
          onCancel={(booking) => setPending({ kind: "cancel", booking })}
          onComplete={async (booking) => {
            const message = await act(booking, "complete", {}, `Visit with ${booking.patient.name} completed`);
            if (message) showToast(message);
          }}
          onApproveSelf={async (booking) => {
            const message = await act(booking, "approve", {}, `Video visit with ${booking.patient.name} confirmed`);
            if (message) showToast(message);
          }}
        />
      )}

      {pending?.kind === "approve" && (
        <ApproveDialog
          booking={pending.booking}
          onClose={() => setPending(null)}
          onConfirm={(doctorId) =>
            act(pending.booking, "approve", { doctor_id: doctorId }, `Video visit with ${pending.booking.patient.name} confirmed`)
          }
        />
      )}
      {(pending?.kind === "reject" || pending?.kind === "cancel") && (
        <ReasonDialog
          action={pending.kind}
          booking={pending.booking}
          onClose={() => setPending(null)}
          onConfirm={(reason) =>
            act(
              pending.booking,
              pending.kind,
              { reason },
              pending.kind === "reject"
                ? "Booking rejected; the patient will be refunded"
                : "Visit cancelled; the patient will be refunded"
            )
          }
        />
      )}
    </div>
  );
}
