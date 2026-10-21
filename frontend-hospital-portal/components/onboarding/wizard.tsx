"use client";

import { useCallback, useEffect, useState } from "react";
import { hardNavigate } from "@/lib/navigation";
import { ApiError, apiFetch } from "@/lib/api";
import { STEPS, type Application } from "@/lib/onboarding-types";
import { signOutNow } from "@/components/session/session-context";
import { OnboardingFrame } from "@/components/onboarding/onboarding-frame";
import {
  AccountStep,
  ContactStep,
  DemoStep,
  DocumentsStep,
  FacilityStep,
  LocationStep,
  ReviewStep,
} from "@/components/onboarding/steps";

type State =
  | { status: "loading" }
  | { status: "signed-out" }
  | { status: "error"; message: string }
  | { status: "ready"; application: Application };

function stepIndex(application: Application): number {
  return Math.max(0, STEPS.findIndex((s) => s.key === application.next_step));
}

/** The application as the wizard shows it; null when the page is being left. */
async function readState(): Promise<State | null> {
  try {
    const application = await apiFetch<Application>("onboarding/application", { redirectOn401: false });
    if (application.status === "approved") {
      hardNavigate("/");
      return null;
    }
    const fixing = new URLSearchParams(window.location.search).get("fix") === "1";
    if (application.status === "submitted" || (application.status === "rejected" && !fixing)) {
      hardNavigate("/under-review");
      return null;
    }
    return { status: "ready", application };
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return { status: "signed-out" };
    return { status: "error", message: err instanceof ApiError ? err.message : "Something went wrong." };
  }
}

/**
 * The application wizard. Every step is saved on the hospital service as it
 * is completed, so a reload or a later sign-in comes back to the first step
 * still missing something.
 */
export function OnboardingWizard() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [step, setStep] = useState(0);

  const show = useCallback((next: State, resume: boolean) => {
    setState(next);
    if (resume && next.status === "ready") setStep(stepIndex(next.application));
  }, []);

  // Loads on arrival (and after the account is created); the state is set
  // when the answer comes back.
  useEffect(() => {
    let cancelled = false;
    void readState().then((next) => {
      if (!cancelled && next) show(next, true);
    });
    return () => {
      cancelled = true;
    };
  }, [show]);

  function saved(application: Application, advance = true) {
    setState({ status: "ready", application });
    if (!advance) return;
    setStep((current) => Math.min(current + 1, STEPS.length - 1));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const back = () => setStep((current) => Math.max(current - 1, 0));
  const footer = state.status === "ready" && (
    <p className="mt-4 text-center text-[11px] text-slate-500">
      Saved as you go: sign in again any time to continue.{" "}
      <button type="button" onClick={() => void signOutNow()} className="font-semibold text-[#1E5852] hover:underline">
        Sign out
      </button>
    </p>
  );

  if (state.status === "loading") {
    return (
      <OnboardingFrame>
        <p role="status" className="py-10 text-center text-xs text-slate-500">
          Loading your application…
        </p>
      </OnboardingFrame>
    );
  }
  if (state.status === "error") {
    return (
      <OnboardingFrame>
        <p role="alert" className="py-6 text-center text-sm text-red-600">
          {state.message}
        </p>
      </OnboardingFrame>
    );
  }
  if (state.status === "signed-out") {
    return (
      <OnboardingFrame step={0} steps={STEPS} wide>
        <AccountStep onCreated={() => void readState().then((next) => next && show(next, true))} />
      </OnboardingFrame>
    );
  }

  const { application } = state;
  const key = STEPS[step].key;
  return (
    <OnboardingFrame step={step} steps={STEPS} wide footer={footer}>
      {application.status === "rejected" && application.rejection_reason && (
        <div data-testid="rejection-note" className="mb-5 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          <p className="font-bold">Endod asked you to fix your application</p>
          <p className="mt-1">{application.rejection_reason}</p>
        </div>
      )}
      {key === "contact" && <ContactStep key={key} application={application} onSaved={saved} />}
      {key === "facility" && <FacilityStep key={key} application={application} onSaved={saved} onBack={back} />}
      {key === "location" && <LocationStep key={key} application={application} onSaved={saved} onBack={back} />}
      {key === "documents" && (
        <DocumentsStep
          key={key}
          application={application}
          onSaved={saved}
          onChanged={(a) => saved(a, false)}
          onBack={back}
        />
      )}
      {key === "demo" && (
        <DemoStep
          key={key}
          application={application}
          onChanged={(a) => saved(a, false)}
          onBack={back}
          onNext={() => setStep(STEPS.length - 1)}
        />
      )}
      {key === "review" && (
        <ReviewStep
          key={key}
          application={application}
          onBack={back}
          onEdit={setStep}
          onSubmitted={() => hardNavigate("/under-review")}
        />
      )}
    </OnboardingFrame>
  );
}
