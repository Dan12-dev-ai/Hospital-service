import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { MedicalRecordsPage } from "@/components/medical-records/medical-records-page";

export const metadata: Metadata = {
  title: "Dedan Health OS • Medical Records",
};

export default function MedicalRecordsRoute() {
  return (
    <PortalShell>
      <MedicalRecordsPage />
    </PortalShell>
  );
}
