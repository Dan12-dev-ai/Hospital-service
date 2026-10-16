import type { Metadata } from "next";
import { AppointmentsDirectory } from "@/components/appointments/appointments-directory";

export const metadata: Metadata = {
  title: "Dedan Health OS • Appointments",
};

export default function AppointmentsPage() {
  return <AppointmentsDirectory />;
}

