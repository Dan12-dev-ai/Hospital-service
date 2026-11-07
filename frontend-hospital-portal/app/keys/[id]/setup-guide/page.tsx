import { Suspense } from "react";
import type { Metadata } from "next";
import { SetupGuide } from "@/components/keys/setup-guide";
import { SetupGuideSkeleton } from "@/components/common/page-skeletons";

export const metadata: Metadata = {
  title: "Setup guide • Endod Developers",
};

export default function SetupGuideRoute() {
  // A dynamic route: the connection id is only known at request time.
  return (
    <Suspense fallback={<SetupGuideSkeleton />}>
      <SetupGuide />
    </Suspense>
  );
}
