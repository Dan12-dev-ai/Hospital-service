import { Suspense } from "react";
import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { LoadingState } from "@/components/common/states";
import { VideoVisit } from "@/components/visit/video-visit";

export const metadata: Metadata = {
  title: "Dedan Health OS • Video visit",
};

export default function VisitPage() {
  // A dynamic route: the URL (the booking id, and the sidebar's active link)
  // is only known at request time, so the whole shell streams in.
  return (
    <Suspense fallback={<LoadingState label="Opening the visit…" className="m-6" />}>
      <PortalShell>
        <VideoVisit />
      </PortalShell>
    </Suspense>
  );
}
