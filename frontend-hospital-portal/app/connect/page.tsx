import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { ConnectPage } from "@/components/connect/connect-page";

export const metadata: Metadata = {
  title: "Dedan Health OS • Connect your system",
};

export default function ConnectRoute() {
  return (
    <PortalShell>
      <ConnectPage />
    </PortalShell>
  );
}
