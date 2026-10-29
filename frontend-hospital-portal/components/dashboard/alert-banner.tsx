"use client";

import { useState } from "react";
import Link from "next/link";
import { Video, X } from "lucide-react";

import { useSignedIn } from "@/components/session/session-context";
import { useApi } from "@/lib/api";
import type { BookingList } from "@/lib/api-types";
import { BOOKING_VIEWERS } from "@/lib/booking-rules";

/** Video visits from the Endod app that are waiting for a doctor's approval. */
export function AlertBanner() {
  const signedIn = useSignedIn();
  const [dismissed, setDismissed] = useState(false);
  const canSee = Boolean(signedIn && BOOKING_VIEWERS.includes(signedIn.staff.role));
  const waiting = useApi<BookingList>(canSee ? "bookings?status=awaiting_doctor" : null);
  const count = waiting.data?.items.length ?? 0;

  if (dismissed || !waiting.data || count === 0) return null;
  const next = waiting.data.items[0];

  return (
    <div
      data-testid="awaiting-banner"
      className="flex w-full items-center justify-between gap-4 rounded-2xl bg-black px-5 py-3 text-white shadow-md transition-all duration-300"
    >
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-white/20">
          <Video className="text-[18px] text-neutral-200" />
        </div>
        <div className="truncate text-xs">
          <span className="font-bold text-neutral-200">
            {count === 1 ? "1 video visit awaits" : `${count} video visits await`} a doctor&apos;s approval:
          </span>
          <span className="ml-1 font-semibold text-white">{next.patient.name}</span>
          <span className="mx-1 rounded bg-black/20 px-1.5 py-0.5 font-mono text-[10px] text-neutral-300">
            {next.patient.dedan_id}
          </span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Link
          href="/appointments?status=awaiting_doctor"
          className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-black shadow-sm transition-colors hover:bg-neutral-50"
        >
          Review
        </Link>
        <button
          type="button"
          aria-label="Dismiss alert"
          onClick={() => setDismissed(true)}
          className="text-neutral-200 transition-colors hover:text-white"
        >
          <X className="text-[18px]" />
        </button>
      </div>
    </div>
  );
}
