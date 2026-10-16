import type { Metadata } from "next";
import {
  PlaceholderPage,
  PortalShell,
} from "@/components/dashboard/portal-shell";

export const metadata: Metadata = {
  title: "Dedan Health OS • Billing",
};

export default function BillingPage() {
  return (
    <PortalShell>
      <PlaceholderPage
        title="Billing"
        description="Invoices, insurance claims and payment tracking."
        icon="construction"
      />
    </PortalShell>
  );
}
