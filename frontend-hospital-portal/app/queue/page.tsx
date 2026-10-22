import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { QueueBoardPage } from "@/components/queue/queue-board";

export const metadata: Metadata = {
  title: "Dedan Health OS • Queue",
};

export default function QueuePage() {
  return (
    <PortalShell>
      <QueueBoardPage />
    </PortalShell>
  );
}
