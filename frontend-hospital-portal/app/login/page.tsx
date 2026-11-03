import type { Metadata } from "next";
import { AuthCard } from "@/components/auth/auth-card";
import { LoginForm } from "@/components/auth/login-form";

export const metadata: Metadata = {
  title: "Sign in • Endod Developers",
};

export default function LoginPage() {
  return (
    <AuthCard title="Sign in" subtitle="The Endod developer dashboard, for your hospital's administrators and developers.">
      <LoginForm />
    </AuthCard>
  );
}
