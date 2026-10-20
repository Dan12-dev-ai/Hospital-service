"use client";

import Link from "next/link";
import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import { EmptyState } from "@/components/common/states";
import type { Booking, BookingStatus, Staff } from "@/lib/api-types";
import {
  BOOKING_STATUS_LABELS,
  canApprove,
  canCancel,
  canComplete,
  canJoinVideo,
  canReject,
  videoWindowOpen,
} from "@/lib/booking-rules";
import { formatBirr, formatDateTime, initialsOf, titleCase } from "@/lib/format";
import { useNow } from "@/lib/use-now";

const COLUMNS = [
  { label: "Patient & Endod ID", px: "px-space-lg" },
  { label: "Scheduled Time & Type", px: "px-space-md" },
  { label: "Doctor", px: "px-space-md" },
  { label: "Status", px: "px-space-md" },
  { label: "Price / Notes", px: "px-space-md" },
  { label: "Actions", px: "px-space-lg", alignRight: true },
];

const STATUS_STYLES: Record<BookingStatus, { pill: string; dot: string }> = {
  awaiting_doctor: { pill: "bg-amber-50 text-amber-800", dot: "bg-amber-500 animate-pulse" },
  confirmed: { pill: "bg-primary-fixed text-on-primary-fixed-variant", dot: "bg-primary" },
  completed: { pill: "bg-surface-container-high text-primary-container", dot: "bg-primary-container" },
  rejected: { pill: "bg-rose-50 text-rose-700", dot: "bg-rose-500" },
  cancelled: { pill: "bg-slate-100 text-slate-600", dot: "bg-slate-400" },
};

type Handlers = {
  onApprove: (booking: Booking) => void;
  onApproveSelf: (booking: Booking) => void;
  onReject: (booking: Booking) => void;
  onCancel: (booking: Booking) => void;
  onComplete: (booking: Booking) => void;
};

export function BookingsTable({
  rows,
  staff,
  timeZone,
  busyId,
  filtered,
  ...handlers
}: {
  rows: Booking[];
  staff: Staff;
  timeZone: string;
  busyId: string | null;
  filtered: boolean;
} & Handlers) {
  const now = useNow();
  return (
    <div className="mb-space-lg flex flex-col overflow-hidden rounded-2xl bg-surface-container-lowest shadow-soft">
      <div className="custom-scrollbar overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="bg-surface-container-low font-label-sm text-label-sm uppercase tracking-wider text-outline">
              {COLUMNS.map((column) => (
                <th key={column.label} className={`${column.px} py-3.5 font-medium ${column.alignRight ? "text-right" : ""}`}>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-variant font-body-md text-body-md">
            {rows.length > 0 ? (
              rows.map((booking) => (
                <BookingRow
                  key={booking.id}
                  booking={booking}
                  staff={staff}
                  timeZone={timeZone}
                  busy={busyId === booking.id}
                  now={now}
                  {...handlers}
                />
              ))
            ) : (
              <tr>
                <td colSpan={COLUMNS.length}>
                  {filtered ? (
                    <EmptyState icon="filter_alt_off" title="No bookings match these filters." />
                  ) : (
                    <EmptyState icon="event_note" title="No bookings yet">
                      Bookings that patients make for this hospital in the Endod app appear here. Video visits wait for
                      a doctor&apos;s approval; in-person visits are confirmed at once.
                    </EmptyState>
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="bg-surface-container-low px-space-lg py-space-md font-body-sm text-body-sm text-outline">
        Showing <strong className="font-semibold text-on-surface">{rows.length}</strong> bookings
      </div>
    </div>
  );
}

function BookingRow({
  booking,
  staff,
  timeZone,
  busy,
  now,
  onApprove,
  onApproveSelf,
  onReject,
  onCancel,
  onComplete,
}: {
  booking: Booking;
  staff: Staff;
  timeZone: string;
  busy: boolean;
  now: number;
} & Handlers) {
  const style = STATUS_STYLES[booking.status];
  const video = booking.visit_mode === "video";
  // `now` is 0 before the clock has started (server render): no time-based actions yet.
  const completable = now > 0 && canComplete(staff, booking, now);
  const joinable = canJoinVideo(staff, booking);
  const windowOpen = now > 0 && videoWindowOpen(booking, now);

  return (
    <tr data-testid="booking-row" data-booking-id={booking.id} data-status={booking.status} className="transition-colors hover:bg-surface-container-low/70">
      <td className="px-space-lg py-4">
        <div className="flex items-center gap-space-sm">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-pine-light font-label-md text-label-md font-bold text-pine-green shadow-xs">
            {initialsOf(booking.patient.name)}
          </div>
          <div className="flex min-w-0 flex-col">
            <span className="truncate font-label-md text-label-md font-semibold text-on-surface">{booking.patient.name}</span>
            <div className="flex items-center gap-1.5 font-label-sm text-label-sm text-outline">
              <span>{booking.patient.dedan_id}</span>
              {booking.patient.phone && (
                <>
                  <span>•</span>
                  <span>{booking.patient.phone}</span>
                </>
              )}
            </div>
          </div>
        </div>
      </td>

      <td className="px-space-md py-4">
        <div className="flex flex-col">
          <span className="flex items-center gap-1 font-label-md text-label-md font-semibold text-on-surface">
            <Icon name="schedule" className="text-[15px] text-outline" />
            {formatDateTime(booking.scheduled_at, timeZone)}
          </span>
          <span className="flex items-center gap-1 font-body-sm text-body-sm text-outline">
            <Icon name={video ? "videocam" : "directions_walk"} className="text-[14px]" />
            {video ? "Video visit" : "In person"} • {booking.duration_minutes} min
            {booking.service ? ` • ${titleCase(booking.service)}` : ""}
          </span>
        </div>
      </td>

      <td className="px-space-md py-4">
        <span className="font-label-md text-label-md font-medium text-on-surface">
          {booking.doctor?.full_name || (booking.status === "awaiting_doctor" ? "Not assigned yet" : "—")}
        </span>
      </td>

      <td className="px-space-md py-4">
        <span data-testid="booking-status" className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-1 font-label-sm text-label-sm", style.pill)}>
          <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} />
          {BOOKING_STATUS_LABELS[booking.status]}
        </span>
      </td>

      <td className="max-w-[16rem] px-space-md py-4">
        <div className="flex flex-col gap-0.5">
          <span className="font-label-md text-label-md text-on-surface">{formatBirr(booking.price)}</span>
          {booking.notes && <span className="truncate font-body-sm text-body-sm text-outline" title={booking.notes}>{booking.notes}</span>}
          {booking.reason && (
            <span data-testid="booking-reason" className="font-body-sm text-body-sm text-rose-700">
              Reason: {booking.reason}
            </span>
          )}
        </div>
      </td>

      <td className="px-space-lg py-4 text-right">
        <div className="inline-flex flex-wrap items-center justify-end gap-1">
          {joinable &&
            (windowOpen ? (
              <Link href={`/visit/${booking.id}`} className="inline-flex items-center gap-1 rounded-lg bg-primary-container px-3 py-1.5 font-label-sm text-label-sm font-medium text-on-primary shadow-xs hover:bg-primary">
                <Icon name="videocam" className="text-[16px]" />
                Join video
              </Link>
            ) : (
              <span title="The video room opens 30 minutes before the visit." className="inline-flex cursor-not-allowed items-center gap-1 rounded-lg bg-surface-container px-3 py-1.5 font-label-sm text-label-sm text-outline">
                <Icon name="videocam_off" className="text-[16px]" />
                Join video
              </span>
            ))}
          {canApprove(staff, booking) && (
            <ActionButton
              primary
              disabled={busy}
              onClick={() => (staff.role === "doctor" ? onApproveSelf(booking) : onApprove(booking))}
            >
              Approve
            </ActionButton>
          )}
          {canReject(staff, booking) && (
            <ActionButton disabled={busy} onClick={() => onReject(booking)}>
              Reject
            </ActionButton>
          )}
          {completable && (
            <ActionButton disabled={busy} onClick={() => onComplete(booking)}>
              Complete
            </ActionButton>
          )}
          {canCancel(staff, booking) && (
            <ActionButton disabled={busy} onClick={() => onCancel(booking)}>
              Cancel
            </ActionButton>
          )}
        </div>
      </td>
    </tr>
  );
}

function ActionButton({
  children,
  onClick,
  primary,
  disabled,
}: {
  children: string;
  onClick: () => void;
  primary?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded-lg px-3 py-1.5 font-label-sm text-label-sm font-medium transition-colors disabled:opacity-50",
        primary
          ? "bg-primary-container text-on-primary shadow-xs hover:bg-primary"
          : "bg-surface-container text-on-surface hover:bg-primary-container hover:text-on-primary"
      )}
    >
      {children}
    </button>
  );
}
