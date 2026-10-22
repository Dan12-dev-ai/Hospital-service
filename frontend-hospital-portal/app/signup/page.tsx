import { redirect } from "next/navigation";

/** Sign-up is now the first step of the onboarding application. */
export default function SignupPage() {
  redirect("/onboarding");
}
