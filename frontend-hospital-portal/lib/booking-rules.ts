import type { Booking, BookingStatus, Role, Staff } from "@/lib/api-types";

/**
 * Who may do what with an Endod booking. These mirror the backend's rules
 * (backend-hospital/app/api/bookings.py and app/bookings.py) so the portal
 * only offers actions the backend will accept; the backend still decides.
 */

export const BOOKING_VIEWERS: Role[] = ["admin", "doctor", "nurse", "reception"];

export const BOOKING_STATUS_LABELS: Record<BookingStatus, string> = {
  awaiting_doctor: "Awaiting doctor",
  confirmed: "Confirmed",
  rejected: "Rejected",
  cancelled: "Cancelled",
  completed: "Completed",
};

/** A video visit belongs to its doctor (or an admin) for cancelling and completing. */
function ownsVideo(staff: Staff, booking: Booking): boolean {
  if (booking.visit_mode !== "video" || !booking.doctor || staff.role === "admin") return true;
  return booking.doctor.id === staff.id;
}

export function canApprove(staff: Staff, booking: Booking): boolean {
  return (
    (staff.role === "doctor" || staff.role === "admin") &&
    booking.visit_mode === "video" &&
    booking.status === "awaiting_doctor"
  );
}

export function canReject(staff: Staff, booking: Booking): boolean {
  return (staff.role === "doctor" || staff.role === "admin") && booking.status === "awaiting_doctor";
}

export function canCancel(staff: Staff, booking: Booking): boolean {
  if (!["admin", "reception", "doctor"].includes(staff.role)) return false;
  if (booking.status !== "confirmed") return false;
  if (booking.visit_mode === "video" && staff.role === "reception") return false;
  return ownsVideo(staff, booking);
}

export function canComplete(staff: Staff, booking: Booking, now: number = Date.now()): boolean {
  if (!["admin", "doctor", "nurse"].includes(staff.role)) return false;
  if (booking.status !== "confirmed") return false;
  if (new Date(booking.scheduled_at).getTime() > now) return false;
  if (booking.visit_mode === "video" && staff.role === "nurse") return false;
  return ownsVideo(staff, booking);
}

/** Only the visit's own doctor joins the call (as its moderator). */
export function canJoinVideo(staff: Staff, booking: Booking): boolean {
  return (
    staff.role === "doctor" &&
    booking.visit_mode === "video" &&
    booking.status === "confirmed" &&
    booking.has_video_room &&
    booking.doctor?.id === staff.id
  );
}

/** The room opens 30 minutes before the visit and closes an hour after it was due to end. */
export function videoWindow(booking: Booking): { opens: number; closes: number } {
  const start = new Date(booking.scheduled_at).getTime();
  return { opens: start - 30 * 60_000, closes: start + (booking.duration_minutes + 60) * 60_000 };
}

export function videoWindowOpen(booking: Booking, now: number = Date.now()): boolean {
  const { opens, closes } = videoWindow(booking);
  return opens <= now && now <= closes;
}
