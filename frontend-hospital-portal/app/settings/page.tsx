import type { Metadata } from "next";
import {
  PlaceholderPage,
  PortalShell,
} from "@/components/dashboard/portal-shell";

export const metadata: Metadata = {
  title: "Dedan Health OS • Settings",
};

export default function SettingsPage() {
  return (
    <PortalShell>
      <PlaceholderPage
        title="Settings"
        description="Portal preferences, users, roles and integrations."
        icon="construction"
      />
    </PortalShell>
  );
}
