import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { SamplePageNotice } from "@/components/common/states";
import { PharmacyDirectory } from "@/components/pharmacy/pharmacy-directory";

export const metadata: Metadata = {
  title: "Dedan Health OS • Pharmacy",
};

export default function PharmacyPage() {
  return (
    <PortalShell>
      <SamplePageNotice module="The pharmacy" />
      <PharmacyDirectory />
    </PortalShell>
  );
}
