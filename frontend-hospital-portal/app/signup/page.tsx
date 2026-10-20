import type { Metadata } from "next";
import { AuthCard } from "@/components/auth/auth-card";
import { SignupForm } from "@/components/auth/signup-form";

export const metadata: Metadata = {
  title: "Sign up your hospital • Endod hospital portal",
};

export default function SignupPage() {
  return (
    <AuthCard
      wide
      title="Sign up your hospital"
      subtitle="Create your hospital's account and its first administrator. Endod approves new hospitals before patients can book them."
    >
      <SignupForm />
    </AuthCard>
  );
}
