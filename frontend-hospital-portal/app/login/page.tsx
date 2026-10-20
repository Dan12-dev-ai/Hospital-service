import type { Metadata } from "next";
import { AuthCard } from "@/components/auth/auth-card";
import { LoginForm } from "@/components/auth/login-form";

export const metadata: Metadata = {
  title: "Sign in • Endod hospital portal",
};

export default function LoginPage() {
  return (
    <AuthCard title="Sign in" subtitle="Use the staff account your hospital's administrator gave you.">
      <LoginForm />
    </AuthCard>
  );
}
