import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { HospitalSettings } from "@/components/settings/hospital-settings";

export const metadata: Metadata = {
  title: "Dedan Health OS • Settings",
};

export default function SettingsPage() {
  return (
    <PortalShell>
      <HospitalSettings />
    </PortalShell>
  );
}
