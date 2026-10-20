import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { SamplePageNotice } from "@/components/common/states";
import { ReportsDirectory } from "@/components/reports/reports-directory";

export const metadata: Metadata = {
  title: "Dedan Health OS • Reports",
};

export default function ReportsPage() {
  return (
    <PortalShell>
      <SamplePageNotice module="Reporting" />
      <ReportsDirectory />
    </PortalShell>
  );
}
