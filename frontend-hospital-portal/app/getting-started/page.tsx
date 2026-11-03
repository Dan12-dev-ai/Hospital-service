import type { Metadata } from "next";
import { DashboardShell } from "@/components/shell/dashboard-shell";
import { GettingStartedPage } from "@/components/getting-started/getting-started-page";

export const metadata: Metadata = {
  title: "Getting started • Endod Developers",
};

export default function Page() {
  return (
    <DashboardShell>
      <GettingStartedPage />
    </DashboardShell>
  );
}
