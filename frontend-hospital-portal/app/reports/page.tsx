import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { ReportsDirectory } from "@/components/reports/reports-directory";

export const metadata: Metadata = {
  title: "Dedan Health OS • Reports",
};

export default function ReportsPage() {
  return (
    <PortalShell>
      <ReportsDirectory />
    </PortalShell>
  );
}
