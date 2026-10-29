"use client";

import Link from "next/link";
import { Calendar, User } from "lucide-react";

import { useSignedIn } from "@/components/session/session-context";
import { BOOKING_VIEWERS } from "@/lib/booking-rules";

export function PageHeader() {
  const signedIn = useSignedIn();
  const canSeeBookings = Boolean(signedIn && BOOKING_VIEWERS.includes(signedIn.staff.role));

  return (
    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Dashboard</h1>
        <p className="mt-0.5 text-xs text-slate-500">
          Welcome back{signedIn ? `, ${signedIn.staff.full_name}` : ""}! Here&apos;s what&apos;s happening today
          {signedIn ? ` at ${signedIn.hospital.name}` : ""}.
        </p>
      </div>
      <div className="flex items-center gap-2.5">
        {canSeeBookings && (
          <Link
            href="/appointments"
            className="flex items-center gap-1.5 rounded-2xl border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 shadow-sm transition-colors hover:bg-slate-50"
          >
            <Calendar className="text-[18px]" />
            <span>Bookings</span>
          </Link>
        )}
        <Link
          href="/patients"
          className="flex items-center gap-1.5 rounded-2xl bg-black px-4 py-2 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-[#1f2937]"
        >
          <User className="text-[18px]" />
          <span>Patients</span>
        </Link>
      </div>
    </div>
  );
}
