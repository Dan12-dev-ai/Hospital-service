import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { ImportPage } from "@/components/import/import-page";

export const metadata: Metadata = {
  title: "Dedan Health OS • Import records",
};

export default function ImportRoute() {
  return (
    <PortalShell>
      <ImportPage />
    </PortalShell>
  );
}
