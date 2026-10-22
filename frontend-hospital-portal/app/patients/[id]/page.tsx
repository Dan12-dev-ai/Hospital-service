import { Suspense } from "react";
import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { LoadingState } from "@/components/common/states";
import { PatientChart } from "@/components/patient/patient-chart";

export const metadata: Metadata = {
  title: "Dedan Health OS • Patient",
};

export default function PatientPage() {
  // A dynamic route: the patient id is only known at request time.
  return (
    <Suspense fallback={<LoadingState label="Opening the patient…" className="m-6" />}>
      <PortalShell>
        <PatientChart />
      </PortalShell>
    </Suspense>
  );
}
