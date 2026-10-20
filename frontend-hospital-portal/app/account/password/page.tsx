import type { Metadata } from "next";
import { AuthCard } from "@/components/auth/auth-card";
import { ChangePasswordForm } from "@/components/auth/change-password-form";

export const metadata: Metadata = {
  title: "Change password • Endod hospital portal",
};

export default function ChangePasswordPage() {
  return (
    <AuthCard title="Change password">
      <ChangePasswordForm />
    </AuthCard>
  );
}
