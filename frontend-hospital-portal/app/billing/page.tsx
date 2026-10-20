import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { SamplePageNotice } from "@/components/common/states";
import { BillingDirectory } from "@/components/billing/billing-directory";

export const metadata: Metadata = {
  title: "Dedan Health OS • Billing",
};

export default function BillingPage() {
  return (
    <PortalShell>
      <SamplePageNotice module="Billing" />
      <BillingDirectory />
    </PortalShell>
  );
}
