import type { Metadata } from "next";
import {
  PlaceholderPage,
  PortalShell,
} from "@/components/dashboard/portal-shell";

export const metadata: Metadata = {
  title: "Dedan Health OS • Reports",
};

export default function ReportsPage() {
  return (
    <PortalShell>
      <PlaceholderPage
        title="Reports"
        description="Clinical, operational and MOH regulatory reports."
        icon="construction"
      />
    </PortalShell>
  );
}
