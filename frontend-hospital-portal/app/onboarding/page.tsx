import type { Metadata } from "next";
import { OnboardingWizard } from "@/components/onboarding/wizard";

export const metadata: Metadata = {
  title: "Join Endod • Endod hospital portal",
  description: "Apply to list your hospital or clinic on Endod: your facility, documents and a demo with Endod.",
};

export default function OnboardingPage() {
  return <OnboardingWizard />;
}
