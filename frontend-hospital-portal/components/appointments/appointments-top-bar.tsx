"use client";

import { useSyncExternalStore } from "react";
import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { signedInDoctor } from "@/lib/dashboard-data";

const EAT_TIME_ZONE = "Africa/Addis_Ababa";

function formatEatTime() {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: EAT_TIME_ZONE,
  }).format(new Date());
}

function subscribeToClock(onChange: () => void) {
  const interval = setInterval(onChange, 30_000);
  return () => clearInterval(interval);
}

function useEatClock() {
  return useSyncExternalStore(
    subscribeToClock,
    formatEatTime,
    () => "14:45" // stable snapshot for SSR/prerender
  );
}

export function AppointmentsTopBar() {
  const { showToast } = useDashboard();
  const time = useEatClock();

  return (
    <header className="fixed left-64 right-0 top-0 z-40 flex h-16 items-center justify-between bg-surface-container-lowest/90 px-gutter-lg shadow-[0_1px_8px_rgba(0,0,0,0.04)] backdrop-blur-xl">
      {/* Global search */}
      <div className="flex w-96 items-center gap-space-md">
        <div className="flex w-full items-center gap-space-xs rounded-full bg-surface-container-low px-space-md py-space-xs">
          <Icon name="search" className="text-[18px] text-outline" />
          <input
            type="text"
            placeholder="Search patients, MRN, staff, or drugs..."
            className="w-full bg-transparent font-body-md text-body-md text-on-surface placeholder:text-outline focus:outline-none"
          />
        </div>
      </div>

      {/* Right cluster */}
      <div className="flex items-center gap-space-md">
        {/* Live clock */}
        <div className="flex items-center gap-space-xs rounded-full bg-surface-container-low px-space-md py-space-xs">
          <span className="h-2 w-2 animate-pulse rounded-full bg-secondary" />
          <Icon name="schedule" className="text-[16px] text-outline" />
          <span className="font-label-md text-label-md text-on-surface">
            Addis Ababa (EAT) {time}
          </span>
        </div>

        {/* Language toggle */}
        <div className="flex items-center rounded-full bg-surface-container-low p-0.5 font-label-sm text-label-sm">
          <button
            type="button"
            onClick={() => showToast("Language set to English")}
            className="rounded-full bg-primary-container px-space-sm py-0.5 font-semibold text-on-primary shadow-xs"
          >
            EN
          </button>
          <button
            type="button"
            onClick={() => showToast("ቋንቋ ወደ አማርኛ ተቀይሯል")}
            className="rounded-full px-space-sm py-0.5 text-on-surface-variant transition-colors hover:text-on-surface"
          >
            አማርኛ
          </button>
        </div>

        {/* Notifications */}
        <button
          type="button"
          aria-label="Notifications"
          onClick={() => showToast("You have 3 new appointment alerts")}
          className="relative flex h-9 w-9 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-container-high"
        >
          <Icon name="notifications" className="text-[20px]" />
          <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-error" />
        </button>

        {/* Profile */}
        <div className="flex items-center gap-space-sm pl-space-xs">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary">
            <Icon name="person" className="text-[18px] text-on-primary" />
          </div>
          <div className="hidden flex-col text-left lg:flex">
            <span className="font-label-md text-label-md leading-tight text-on-surface">
              {signedInDoctor.name}
            </span>
            <span className="font-label-sm text-label-sm leading-tight text-outline">
              Chief Medical Officer
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}

export { cn };
