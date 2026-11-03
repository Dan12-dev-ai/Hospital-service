import type { Metadata } from "next";
import { DashboardShell } from "@/components/shell/dashboard-shell";
import { KeysPage } from "@/components/keys/keys-page";

export const metadata: Metadata = {
  title: "API keys • Endod Developers",
};

export default function Page() {
  return (
    <DashboardShell>
      <KeysPage />
    </DashboardShell>
  );
}
