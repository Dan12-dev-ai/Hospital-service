import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { FollowUpPage } from "@/components/followup/followup-page";

export const metadata: Metadata = {
  title: "Dedan Health OS • Patient follow-up",
};

export default function FollowupPage() {
  return (
    <PortalShell>
      <FollowUpPage />
    </PortalShell>
  );
}
