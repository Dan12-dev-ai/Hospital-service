import type { Metadata } from "next";
import { DashboardShell } from "@/components/shell/dashboard-shell";
import { PlaygroundPage } from "@/components/playground/playground-page";

export const metadata: Metadata = {
  title: "Playground • Endod Developers",
};

export default function Page() {
  return (
    <DashboardShell wide>
      <PlaygroundPage />
    </DashboardShell>
  );
}
