import type { Metadata } from "next";
import { UnderReview } from "@/components/onboarding/under-review";

export const metadata: Metadata = {
  title: "Under review • Endod hospital portal",
};

export default function UnderReviewPage() {
  return <UnderReview />;
}
