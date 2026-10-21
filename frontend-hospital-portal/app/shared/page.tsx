import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { SharedRecordsPage } from "@/components/patient/shared-page";

export const metadata: Metadata = {
  title: "Dedan Health OS • Shared records",
};

export default function SharedPage() {
  return (
    <PortalShell>
      <SharedRecordsPage />
    </PortalShell>
  );
}
