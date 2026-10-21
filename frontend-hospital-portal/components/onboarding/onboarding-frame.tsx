import type { ReactNode } from "react";
import { cn } from "cn";
import { Icon } from "@/components/ui/icon";

/**
 * The onboarding card, in the Endod patient app's onboarding style: a soft
 * teal page, one white rounded card, the brand, then "Step n of m" with a
 * progress bar and the step names.
 */
export function OnboardingFrame({
  children,
  step,
  steps,
  wide = false,
  footer,
}: {
  children: ReactNode;
  /** 0-based; omitted on pages that are not a step (Under review). */
  step?: number;
  steps?: { key: string; short: string }[];
  wide?: boolean;
  footer?: ReactNode;
}) {
  const total = steps?.length ?? 0;
  const progress = step === undefined || !total ? 0 : ((step + 1) / total) * 100;
  return (
    <main
      data-testid="onboarding-frame"
      className="flex min-h-screen w-full items-start justify-center bg-[#DDE9E6] px-4 py-8 text-slate-800 sm:items-center sm:px-8"
    >
      <div className={cn("w-full", wide ? "max-w-[760px]" : "max-w-[600px]")}>
        <div className="rounded-[32px] border border-slate-100 bg-white p-6 shadow-xl shadow-teal-950/5 sm:p-10">
          <div className="mb-7">
            <div className="mb-5 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#1E5852] text-white">
                <Icon name="local_hospital" className="text-[22px]" />
              </div>
              <div>
                <p className="text-2xl font-extrabold leading-none tracking-tight text-[#12302C]">Endod</p>
                <p className="mt-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  Hospitals and clinics
                </p>
              </div>
            </div>
            {step !== undefined && steps && (
              <>
                <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
                  <span data-testid="onboarding-step-of">
                    Step {step + 1} of {total}
                  </span>
                  <span>{Math.round(progress)}%</span>
                </div>
                <div
                  className="h-1.5 w-full overflow-hidden rounded-full bg-[#F2F5F5]"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(progress)}
                  aria-label="Application progress"
                >
                  <div
                    className="h-full rounded-full bg-[#1E5852] transition-all duration-500 ease-out"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <ol className="mt-3 hidden grid-cols-6 gap-1 sm:grid" aria-label="Steps">
                  {steps.map((item, index) => (
                    <li
                      key={item.key}
                      aria-current={index === step ? "step" : undefined}
                      className={cn(
                        "truncate text-center text-[11px]",
                        index === step
                          ? "font-semibold text-[#1E5852]"
                          : index < step
                            ? "text-slate-500"
                            : "text-slate-300"
                      )}
                    >
                      {item.short}
                    </li>
                  ))}
                </ol>
              </>
            )}
          </div>
          {children}
        </div>
        {footer ?? (
          <p className="mt-4 text-center text-[11px] text-slate-500">
            Endod checks every hospital and clinic before patients can book it.
          </p>
        )}
      </div>
    </main>
  );
}

export const stepHeadingClass = "font-serif text-3xl font-medium tracking-tight text-[#12302C] sm:text-[34px]";
export const fieldLabelClass = "mb-1.5 block text-xs font-semibold text-[#12302C]";
export const fieldClass =
  "w-full rounded-xl border border-[#E2E8F0] bg-white px-4 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 focus:border-[#1E5852] focus:outline-none focus:ring-2 focus:ring-[#1E5852]/15 disabled:cursor-not-allowed disabled:opacity-60";
export const nextButtonClass =
  "inline-flex items-center justify-center gap-1.5 rounded-full bg-[#1E5852] px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#174640] disabled:cursor-not-allowed disabled:opacity-50";
export const backButtonClass =
  "rounded-full px-5 py-3 text-sm font-medium text-slate-500 transition-colors hover:text-[#12302C] disabled:cursor-not-allowed disabled:opacity-40";
export const softButtonClass =
  "inline-flex items-center justify-center gap-1.5 rounded-full border border-[#E2E8F0] bg-[#F8FAFB] px-4 py-2 text-xs font-semibold text-[#12302C] transition-colors hover:border-[#1E5852]/40 disabled:cursor-not-allowed disabled:opacity-50";

/** A choice card (a selected one has the brand border and tint). */
export function choiceClass(selected: boolean): string {
  return cn(
    "cursor-pointer rounded-xl border px-4 py-3 text-sm font-medium transition-all",
    selected
      ? "border-[#1E5852] bg-[#F2F8F7] font-semibold text-[#12302C]"
      : "border-[#E2E8F0] bg-[#F8FAFB] text-slate-500 hover:border-[#1E5852]/40 hover:text-[#12302C]"
  );
}

export function StepError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      data-testid="form-error"
      className="mt-4 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-600"
    >
      {message}
    </p>
  );
}
