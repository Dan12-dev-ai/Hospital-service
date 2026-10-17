import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { AppointmentsDirectory } from "@/components/appointments/appointments-directory";

export const metadata: Metadata = {
  title: "Dedan Health OS • Appointments",
};

export default function AppointmentsPage() {
  return (
    <PortalShell showTopBar={false}>
      <AppointmentsDirectory />
    </PortalShell>
  );
}
