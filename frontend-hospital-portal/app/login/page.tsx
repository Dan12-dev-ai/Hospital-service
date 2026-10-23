import type { Metadata } from "next";
import { AuthCard } from "@/components/auth/auth-card";
import { LoginForm } from "@/components/auth/login-form";
import { InstallPwaButton } from "@/components/pwa/install-button";

export const metadata: Metadata = {
  title: "Sign in • Endod hospital portal",
};

export default function LoginPage() {
  return (
    <AuthCard title="Sign in" subtitle="Use the staff account your hospital's administrator gave you.">
      <LoginForm />
      <div className="mt-4 flex justify-center">
        <InstallPwaButton />
      </div>
    </AuthCard>
  );
}
