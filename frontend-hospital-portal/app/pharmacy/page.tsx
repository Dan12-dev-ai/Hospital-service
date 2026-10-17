import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { PharmacyDirectory } from "@/components/pharmacy/pharmacy-directory";

export const metadata: Metadata = {
  title: "Dedan Health OS • Pharmacy",
};

export default function PharmacyPage() {
  return (
    <PortalShell>
      <PharmacyDirectory />
    </PortalShell>
  );
}
