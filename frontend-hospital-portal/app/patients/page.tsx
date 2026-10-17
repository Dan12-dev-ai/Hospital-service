import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { PatientsDirectory } from "@/components/patients/patients-directory";

export const metadata: Metadata = {
  title: "Dedan Health OS • Patients",
};

export default function PatientsPage() {
  return (
    <PortalShell showTopBar={false}>
      <PatientsDirectory />
    </PortalShell>
  );
}
