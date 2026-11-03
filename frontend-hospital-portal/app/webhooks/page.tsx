import type { Metadata } from "next";
import { DashboardShell } from "@/components/shell/dashboard-shell";
import { WebhooksPage } from "@/components/webhooks/webhooks-page";

export const metadata: Metadata = {
  title: "Webhooks • Endod Developers",
};

export default function Page() {
  return (
    <DashboardShell>
      <WebhooksPage />
    </DashboardShell>
  );
}
