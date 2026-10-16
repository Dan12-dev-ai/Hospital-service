import type { Metadata } from "next";
import {
  PlaceholderPage,
  PortalShell,
} from "@/components/dashboard/portal-shell";

export const metadata: Metadata = {
  title: "Dedan Health OS • Patients",
};

export default function PatientsPage() {
  return (
    <PortalShell>
      <PlaceholderPage
        title="Patients"
        description="Patient registry, records and digital health IDs."
        icon="construction"
      />
    </PortalShell>
  );
}
