"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Icon } from "@/components/ui/icon";
import { useSignedIn } from "@/components/session/session-context";
import { MISSING_LABELS, type Hospital } from "@/lib/api-types";

export function missingText(hospital: Hospital): string {
  return hospital.missing_for_listing.map((key) => MISSING_LABELS[key] ?? key.replace(/_/g, " ")).join(" and ");
}

/** The settings field to fill first for the listing (the page focuses it). */
export function settingsLinkFor(hospital: Hospital): string {
  const first = hospital.missing_for_listing[0];
  return first ? `/settings?focus=${encodeURIComponent(first)}` : "/settings";
}

/** Set (per browser tab) once an admin has been sent to Settings for the listing. */
const REDIRECTED_KEY = "endod.listing-redirected.";

/**
 * Says where the hospital is in Endod's onboarding, on every portal page:
 * waiting for Endod's approval, suspended, or approved but not yet listed
 * for patients because the listing is incomplete.
 */
export function HospitalStatusBanner() {
  const signedIn = useSignedIn();
  const pathname = usePathname();
  // Settings shows the listing status (and what is missing) itself.
  if (!signedIn || pathname === "/settings") return null;
  const { hospital, staff } = signedIn;
  const isAdmin = staff.role === "admin";

  if (hospital.status === "pending") {
    return (
      <div
        data-testid="hospital-status-banner"
        data-status="pending"
        className="flex flex-col gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-5 py-3 text-xs text-amber-900 sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="flex items-start gap-3">
          <Icon name="hourglass_top" className="mt-0.5 text-[20px] text-amber-600" />
          <div>
            <p className="font-bold">Pending approval by Endod</p>
            <p className="mt-0.5">
              {hospital.name} is not visible to patients in the Endod app yet, and cannot receive bookings. Endod
              checks every new hospital before listing it. You can use the portal and complete your hospital
              profile meanwhile.
            </p>
          </div>
        </div>
        {isAdmin && (
          <Link
            href="/settings"
            className="shrink-0 rounded-full bg-white px-3 py-1 text-center font-semibold text-amber-800 shadow-sm hover:bg-amber-100"
          >
            Complete profile
          </Link>
        )}
      </div>
    );
  }

  if (hospital.status === "suspended") {
    return (
      <div
        data-testid="hospital-status-banner"
        data-status="suspended"
        className="flex items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-5 py-3 text-xs text-rose-900"
      >
        <Icon name="block" className="mt-0.5 text-[20px] text-rose-600" />
        <div>
          <p className="font-bold">Suspended by Endod</p>
          <p className="mt-0.5">
            {hospital.name} has been taken off the Endod app and cannot receive new bookings. Contact Endod for
            details.
          </p>
        </div>
      </div>
    );
  }

  if (!hospital.listed) {
    return <NotListedCard hospital={hospital} isAdmin={isAdmin} />;
  }

  return null;
}

/**
 * Approved by Endod but hidden from patients: impossible to miss. An admin
 * is also sent to Settings once (per browser tab) when they open the dashboard.
 */
function NotListedCard({ hospital, isAdmin }: { hospital: Hospital; isAdmin: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const target = settingsLinkFor(hospital);
  const onlyPrice = hospital.missing_for_listing.length === 1 && hospital.missing_for_listing[0] === "price_in_person";
  const what = onlyPrice ? "the in-person visit price" : missingText(hospital) || "the missing details";

  useEffect(() => {
    if (!isAdmin || pathname !== "/") return;
    const key = REDIRECTED_KEY + hospital.id;
    try {
      if (window.sessionStorage.getItem(key)) return;
      window.sessionStorage.setItem(key, "1");
    } catch {
      return; // no storage: the card below still says what to do
    }
    router.replace(target);
  }, [isAdmin, pathname, hospital.id, router, target]);

  return (
    <section
      data-testid="hospital-status-banner"
      data-status="unlisted"
      role="alert"
      className="flex flex-col gap-4 rounded-3xl border-2 border-amber-400 bg-amber-50 p-5 text-amber-950 shadow-soft sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex items-start gap-4">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-amber-400 text-amber-950">
          <Icon name="warning" className="text-[24px]" />
        </div>
        <div>
          <p className="text-base font-bold">Patients can&apos;t find {hospital.name} yet</p>
          <p className="mt-1 text-sm">
            Endod approved {hospital.name}, but it stays hidden in the Endod app, and nobody can book it, until{" "}
            {isAdmin ? "you set " : "your hospital's admin sets "}
            <strong>{what}</strong>.
          </p>
          {!isAdmin && (
            <p data-testid="ask-admin" className="mt-1 text-sm font-semibold">
              Ask your hospital&apos;s admin to set {onlyPrice ? "the price" : "this"} in Settings.
            </p>
          )}
        </div>
      </div>
      {isAdmin && (
        <Link
          href={target}
          className="shrink-0 rounded-full bg-black px-5 py-2.5 text-center text-sm font-semibold text-white shadow-sm hover:bg-neutral-800"
        >
          {onlyPrice ? "Set the price now" : "Fix it in Settings"}
        </Link>
      )}
    </section>
  );
}
