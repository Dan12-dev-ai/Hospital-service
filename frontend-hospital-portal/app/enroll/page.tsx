import type { Metadata } from "next";
import { AuthCard } from "@/components/auth/auth-card";
import { EnrollForm } from "@/components/auth/enroll-form";

export const metadata: Metadata = {
  title: "Two-step verification • Endod hospital portal",
};

export default function EnrollPage() {
  return (
    <AuthCard title="Set up two-step verification">
      <EnrollForm />
    </AuthCard>
  );
}
