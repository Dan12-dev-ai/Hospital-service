"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Icon } from "@/components/ui/icon";
import { hardNavigate } from "@/lib/navigation";
import { ApiError, apiFetch } from "@/lib/api";
import { formatDemo, type Application } from "@/lib/onboarding-types";
import { signOutNow } from "@/components/session/session-context";
import { OnboardingFrame, nextButtonClass, softButtonClass, stepHeadingClass } from "@/components/onboarding/onboarding-frame";
import { DemoPicker } from "@/components/onboarding/demo-picker";

const NEXT_STEPS = [
  { icon: "videocam", text: "Meet Endod at your demo: we show you the portal and go through your application." },
  { icon: "fact_check", text: "Endod reviews your license and documents." },
  { icon: "verified", text: "Once approved, you sign in to the full portal: add your staff, prices and doctors." },
  { icon: "storefront", text: "Patients then find and book you in the Endod app." },
];

/**
 * What a hospital sees after submitting, and nothing else until Endod
 * approves it: the facility, the demo time (which it can change) and what
 * happens next; or, if Endod sent the application back, why, with a way to fix it.
 */
export function UnderReview() {
  const [application, setApplication] = useState<Application | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [changing, setChanging] = useState(false);

  useEffect(() => {
    apiFetch<Application>("onboarding/application").then(
      (loaded) => {
        if (loaded.status === "approved") return hardNavigate("/");
        if (loaded.status === "draft") return hardNavigate("/onboarding");
        setApplication(loaded);
      },
      (err: unknown) => setError(err instanceof ApiError ? err.message : "Something went wrong.")
    );
  }, []);

  const footer = (
    <p className="mt-4 text-center text-[11px] text-slate-500">
      Endod will contact you about your application.{" "}
      <button type="button" onClick={() => void signOutNow()} className="font-semibold text-[#1E5852] hover:underline">
        Sign out
      </button>
    </p>
  );

  if (!application) {
    return (
      <OnboardingFrame footer={footer}>
        {error ? (
          <p role="alert" className="py-6 text-center text-sm text-red-600">
            {error}
          </p>
        ) : (
          <p role="status" className="py-10 text-center text-xs text-slate-500">
            Loading…
          </p>
        )}
      </OnboardingFrame>
    );
  }

  const rejected = application.status === "rejected";
  return (
    <OnboardingFrame footer={footer} wide={changing}>
      <div data-testid="under-review" data-status={application.status}>
        <div className="mb-5 flex items-center gap-3">
          <span
            className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl ${rejected ? "bg-amber-100 text-amber-700" : "bg-[#F2F8F7] text-[#1E5852]"}`}
          >
            <Icon name={rejected ? "edit_note" : "hourglass_top"} className="text-[26px]" />
          </span>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              {rejected ? "Changes needed" : "Under review"}
            </p>
            <h1 className={stepHeadingClass} data-testid="under-review-name">
              {application.facility.name}
            </h1>
          </div>
        </div>

        {rejected ? (
          <div data-testid="rejection-reason" className="mb-5 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <p className="font-bold">Endod sent your application back</p>
            <p className="mt-1 text-xs">{application.rejection_reason}</p>
            <Link href="/onboarding?fix=1" className={`${nextButtonClass} mt-3`}>
              Fix and resubmit
            </Link>
          </div>
        ) : (
          <p className="mb-5 text-sm text-slate-600">
            Thank you. Your application is with Endod. Until it is approved, this is the only page of the portal you can use.
          </p>
        )}

        <section className="mb-5 rounded-2xl border border-[#E2E8F0] bg-[#F8FAFB] p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Your demo with Endod</p>
              <p data-testid="under-review-demo" className="mt-1 text-sm font-semibold text-[#12302C]">
                {application.demo ? `${formatDemo(application.demo.demo_at)} (Addis Ababa time)` : "Not booked yet"}
              </p>
              <p className="text-[11px] text-slate-500">30 minutes. The confirmation is texted to {application.contact.phone}.</p>
            </div>
            {!changing && (
              <button type="button" className={softButtonClass} onClick={() => setChanging(true)}>
                <Icon name="event" className="text-[16px]" />
                {application.demo ? "Change time" : "Book a time"}
              </button>
            )}
          </div>
          {changing && (
            <div className="mt-4 border-t border-[#E2E8F0] pt-4">
              <DemoPicker
                current={application.demo?.demo_at ?? null}
                onBooked={(updated) => {
                  setApplication(updated);
                  setChanging(false);
                }}
              />
              <button type="button" className="mt-2 text-xs font-medium text-slate-500 hover:text-[#12302C]" onClick={() => setChanging(false)}>
                Keep the current time
              </button>
            </div>
          )}
        </section>

        <section>
          <p className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">What happens next</p>
          <ol className="space-y-2.5">
            {NEXT_STEPS.map((item) => (
              <li key={item.icon} className="flex items-start gap-3 text-sm text-slate-600">
                <Icon name={item.icon} className="mt-0.5 text-[18px] text-[#1E5852]" />
                <span>{item.text}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </OnboardingFrame>
  );
}
