"use client";

import Image from "next/image";
import { useState } from "react";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import type { AgendaEvent } from "@/lib/dashboard-types";

export function AgendaItem({ event }: { event: AgendaEvent }) {
  const { showToast } = useDashboard();
  const [response, setResponse] = useState<"accepted" | "declined" | null>(
    null
  );

  const respond = (answer: "accepted" | "declined") => {
    setResponse(answer);
    showToast(
      answer === "accepted"
        ? `Accepted: ${event.title}`
        : `Declined: ${event.title}`
    );
  };

  return (
    <div className="relative">
      <div
        className={`absolute -left-4 top-4 h-3 w-3 rounded-full ring-4 ring-white ${event.dotClass}`}
      />
      <div className="flex flex-col gap-2 rounded-3xl bg-black p-4 shadow-sm text-white">
        <div className="flex items-center justify-between">
          <span className="text-xs font-bold">{event.title}</span>
          <span className="rounded-full bg-white/20 px-2 py-0.5 font-mono text-[10px] text-neutral-100">
            {event.time}
          </span>
        </div>
        <p className="text-[11px] text-neutral-100">{event.description}</p>
        <div className="flex items-center justify-between pt-1">
          <div className="flex -space-x-1.5 overflow-hidden">
            {event.attendees.map((avatar, index) => (
              <Image
                key={avatar}
                src={avatar}
                alt={`Attendee ${index + 1}`}
                width={24}
                height={24}
                className="inline-block h-6 w-6 rounded-full ring-2 ring-black"
              />
            ))}
          </div>
          <div className="flex items-center gap-1.5">
            {response ? (
              <span className="rounded-full bg-white/20 px-2 py-1 text-[10px] font-semibold text-neutral-100">
                {response === "accepted" ? "Accepted ✓" : "Declined ✕"}
              </span>
            ) : (
              <>
                <button
                  type="button"
                  aria-label={`Decline ${event.title}`}
                  onClick={() => respond("declined")}
                  title="Decline"
                  className="flex h-6 w-6 items-center justify-center rounded-lg bg-white/20 text-white hover:bg-white/30"
                >
                  <Icon name="close" className="text-[14px]" />
                </button>
                <button
                  type="button"
                  aria-label={`Accept ${event.title}`}
                  onClick={() => respond("accepted")}
                  title="Accept"
                  className="flex h-6 w-6 items-center justify-center rounded-lg bg-white font-bold text-black hover:bg-neutral-50"
                >
                  <Icon name="check" className="text-[14px]" />
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
