"use client";

import Link from "next/link";
import { Icon } from "@/components/ui/icon";
import { useSignedIn } from "@/components/session/session-context";
import { MISSING_LABELS, type Hospital } from "@/lib/api-types";

export function missingText(hospital: Hospital): string {
  return hospital.missing_for_listing.map((key) => MISSING_LABELS[key] ?? key.replace(/_/g, " ")).join(" and ");
}

/**
 * Says where the hospital is in Endod's onboarding, on every portal page:
 * waiting for Endod's approval, suspended, or approved but not yet listed
 * for patients because the listing is incomplete.
 */
export function HospitalStatusBanner() {
  const signedIn = useSignedIn();
  if (!signedIn) return null;
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
    return (
      <div
        data-testid="hospital-status-banner"
        data-status="unlisted"
        className="flex flex-col gap-2 rounded-2xl border border-sky-200 bg-sky-50 px-5 py-3 text-xs text-sky-900 sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="flex items-start gap-3">
          <Icon name="info" className="mt-0.5 text-[20px] text-sky-600" />
          <div>
            <p className="font-bold">Approved by Endod, not listed yet</p>
            <p className="mt-0.5">
              Patients will see {hospital.name} once you add {missingText(hospital) || "the missing details"}.
            </p>
          </div>
        </div>
        {isAdmin && (
          <Link
            href="/settings"
            className="shrink-0 rounded-full bg-white px-3 py-1 text-center font-semibold text-sky-800 shadow-sm hover:bg-sky-100"
          >
            Open settings
          </Link>
        )}
      </div>
    );
  }

  return null;
}
