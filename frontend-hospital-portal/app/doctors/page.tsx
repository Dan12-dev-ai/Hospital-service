import type { Metadata } from "next";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { DoctorsDirectory } from "@/components/doctors/doctors-directory";

export const metadata: Metadata = {
  title: "Dedan Health OS • Doctors",
};

export default function DoctorsPage() {
  return (
    <PortalShell showTopBar={false}>
      <DoctorsDirectory />
    </PortalShell>
  );
}
