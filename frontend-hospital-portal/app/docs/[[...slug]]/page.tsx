import { Suspense } from "react";
import type { Metadata } from "next";
import { LoadingState } from "@/components/common/states";
import { DashboardShell } from "@/components/shell/dashboard-shell";
import { DocsPage } from "@/components/docs/docs-page";

export const metadata: Metadata = {
  title: "Docs • Endod Developers",
};

export default function Page() {
  // The page is chosen by the URL, known only at request time: the whole
  // frame streams in after the static shell.
  return (
    <Suspense fallback={<LoadingState label="Loading the docs…" className="m-10" />}>
      <DashboardShell wide>
        <DocsPage />
      </DashboardShell>
    </Suspense>
  );
}
