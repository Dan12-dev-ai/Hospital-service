import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { BillingDirectory } from "@/components/billing/billing-directory";

export const metadata: Metadata = {
  title: "Dedan Health OS • Billing",
};

export default function BillingPage() {
  return (
    <PortalShell>
      <BillingDirectory />
    </PortalShell>
  );
}
