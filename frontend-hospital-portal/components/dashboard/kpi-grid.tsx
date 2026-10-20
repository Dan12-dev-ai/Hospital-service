"use client";

import { KpiCard } from "@/components/dashboard/kpi-card";
import { useSignedIn } from "@/components/session/session-context";
import { useApi } from "@/lib/api";
import type { BookingList, DoctorList, PatientStats } from "@/lib/api-types";
import { BOOKING_VIEWERS } from "@/lib/booking-rules";
import { sampleInvoiceMetric } from "@/lib/dashboard-data";
import type { KpiMetric } from "@/lib/dashboard-types";

function count(value: number | undefined, loading: boolean, failed: boolean): string {
  if (value !== undefined) return value.toLocaleString("en-US");
  if (failed) return "!";
  return loading ? "…" : "—";
}

/** Real counts from the hospital service; invoices stay sample data until billing exists. */
export function KpiGrid() {
  const signedIn = useSignedIn();
  const canSeeBookings = Boolean(signedIn && BOOKING_VIEWERS.includes(signedIn.staff.role));
  const stats = useApi<PatientStats>(signedIn ? "patients/stats" : null);
  const bookings = useApi<BookingList>(signedIn && canSeeBookings ? "bookings" : null);
  const doctors = useApi<DoctorList>(signedIn ? "doctors" : null);

  const b = bookings.data?.counts;
  const d = doctors.data?.counts;
  const metrics: KpiMetric[] = [
    {
      label: "Total Patients",
      icon: "groups",
      value: count(stats.data?.total, stats.loading, Boolean(stats.error)),
      caption: stats.data ? `${stats.data.registered_today} registered today` : stats.error?.message ?? "Registered at this hospital",
    },
    {
      label: "Open Bookings",
      icon: "calendar_today",
      value: canSeeBookings ? count(b ? b.awaiting_doctor + b.confirmed : undefined, bookings.loading, Boolean(bookings.error)) : "—",
      caption: !canSeeBookings
        ? "Bookings are visible to clinical and front-desk staff"
        : b
          ? `${b.confirmed} confirmed • ${b.awaiting_doctor} awaiting a doctor`
          : bookings.error?.message ?? "From the Endod app",
    },
    sampleInvoiceMetric,
    {
      label: "Doctors on Duty",
      icon: "badge",
      value: count(d ? d["on-duty"] + d["in-consultation"] + d["on-call"] : undefined, doctors.loading, Boolean(doctors.error)),
      caption: d ? `${d["in-consultation"]} in consultation • ${d["on-call"]} on call` : doctors.error?.message ?? "Of all active doctors",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {metrics.map((metric) => (
        <KpiCard key={metric.label} metric={metric} />
      ))}
    </div>
  );
}
