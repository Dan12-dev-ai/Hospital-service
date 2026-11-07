import { Suspense } from "react";
import type { Metadata } from "next";
import { DashboardShell } from "@/components/shell/dashboard-shell";
import { DocsPage } from "@/components/docs/docs-page";
import { DashboardFrameSkeleton } from "@/components/common/page-skeletons";

export const metadata: Metadata = {
  title: "Docs • Endod Developers",
};

export default function Page() {
  // The page is chosen by the URL, known only at request time: the whole
  // frame streams in after the static shell.
  return (
    <Suspense fallback={<DashboardFrameSkeleton path="/docs" wide />}>
      <DashboardShell wide>
        <DocsPage />
      </DashboardShell>
    </Suspense>
  );
}
