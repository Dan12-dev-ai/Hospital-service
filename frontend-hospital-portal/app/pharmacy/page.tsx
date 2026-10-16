import type { Metadata } from "next";
import {
  PlaceholderPage,
  PortalShell,
} from "@/components/dashboard/portal-shell";

export const metadata: Metadata = {
  title: "Dedan Health OS • Pharmacy",
};

export default function PharmacyPage() {
  return (
    <PortalShell>
      <PlaceholderPage
        title="Pharmacy"
        description="Medication stock, prescriptions and dispensing."
        icon="construction"
      />
    </PortalShell>
  );
}
