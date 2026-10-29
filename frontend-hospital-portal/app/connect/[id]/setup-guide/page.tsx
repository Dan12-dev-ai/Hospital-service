import { Suspense } from "react";
import type { Metadata } from "next";
import { LoadingState } from "@/components/common/states";
import { SetupGuide } from "@/components/connect/setup-guide";

export const metadata: Metadata = {
  title: "Dedan Health OS • Setup guide",
};

export default function SetupGuideRoute() {
  // A dynamic route: the connection id is only known at request time.
  return (
    <Suspense fallback={<LoadingState label="Preparing the setup guide…" className="m-6" />}>
      <SetupGuide />
    </Suspense>
  );
}
