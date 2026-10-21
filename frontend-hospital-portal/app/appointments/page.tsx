import { Suspense } from "react";
import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { BookingsDirectory } from "@/components/bookings/bookings-directory";
import { LoadingState } from "@/components/common/states";

export const metadata: Metadata = {
  title: "Dedan Health OS • Patient Booking",
};

export default function AppointmentsPage() {
  return (
    <PortalShell>
      {/* The status filter can come from the URL (?status=awaiting_doctor). */}
      <Suspense fallback={<LoadingState label="Loading bookings…" />}>
        <BookingsDirectory />
      </Suspense>
    </PortalShell>
  );
}
