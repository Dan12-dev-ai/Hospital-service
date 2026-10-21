"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { cn } from "cn";
import { ApiError, apiFetch } from "@/lib/api";
import {
  formatDemo,
  formatTime,
  type Application,
  type DemoSlots,
} from "@/lib/onboarding-types";
import { StepError, choiceClass, nextButtonClass } from "@/components/onboarding/onboarding-frame";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];

/** A calendar date (YYYY-MM-DD, already in Addis time) shown without any timezone shift. */
function dayParts(date: string) {
  const [year, month, day] = date.split("-").map(Number);
  const utc = new Date(Date.UTC(year, month - 1, day));
  return {
    weekday: (utc.getUTCDay() + 6) % 7, // Monday 0
    label: new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", weekday: "short", day: "numeric", month: "short" }).format(utc),
    day,
    month: new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", month: "short" }).format(utc),
    time: utc.getTime(),
  };
}

async function fetchSlots(): Promise<DemoSlots | { error: string }> {
  try {
    return await apiFetch<DemoSlots>("onboarding/demo-slots");
  } catch (err) {
    return { error: err instanceof ApiError ? err.message : "The calendar could not be loaded." };
  }
}

/**
 * The demo calendar: 30-minute slots on weekdays, 09:00 to 17:00 Addis Ababa
 * time, from tomorrow to 30 days ahead. Times other hospitals booked are not
 * shown; if one is taken meanwhile, the backend says so and the calendar reloads.
 */
export function DemoPicker({
  current,
  onBooked,
  confirmLabel,
}: {
  current: string | null;
  onBooked: (application: Application) => void;
  confirmLabel?: string;
}) {
  const [slots, setSlots] = useState<DemoSlots | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const next = await fetchSlots();
    if ("error" in next) setLoadError(next.error);
    else {
      setSlots(next);
      setLoadError(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void fetchSlots().then((next) => {
      if (cancelled) return;
      if ("error" in next) setLoadError(next.error);
      else setSlots(next);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const currentDay = current ? new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Addis_Ababa" }).format(new Date(current)) : null;
  const firstFree = slots?.days.find((d) => d.slots.length > 0)?.date ?? null;
  const shownDay =
    day ?? (currentDay && slots?.days.some((d) => d.date === currentDay) ? currentDay : firstFree);
  const daySlots = slots?.days.find((d) => d.date === shownDay)?.slots ?? [];

  // Weeks of the calendar, Monday to Friday.
  const weeks = useMemo(() => {
    const rows: ({ date: string; free: number } | null)[][] = [];
    let week: ({ date: string; free: number } | null)[] | null = null;
    let weekStart = -1;
    for (const entry of slots?.days ?? []) {
      const parts = dayParts(entry.date);
      const monday = parts.time - parts.weekday * 86_400_000;
      if (monday !== weekStart || !week) {
        week = [null, null, null, null, null];
        rows.push(week);
        weekStart = monday;
      }
      week[parts.weekday] = { date: entry.date, free: entry.slots.length };
    }
    return rows;
  }, [slots]);

  async function book() {
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      const application = await apiFetch<Application>("onboarding/demo", { method: "POST", body: { demo_at: chosen } });
      setChosen(null);
      await load();
      onBooked(application);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The demo could not be booked.");
      if (err instanceof ApiError && err.status === 409) {
        setChosen(null);
        await load();
      }
    } finally {
      setBusy(false);
    }
  }

  if (loadError) return <StepError message={loadError} />;
  if (!slots) {
    return (
      <p role="status" className="py-8 text-center text-xs text-slate-500">
        Loading the calendar…
      </p>
    );
  }

  return (
    <div className="space-y-5" data-testid="demo-picker">
      {current && (
        <p data-testid="demo-current" className="rounded-xl bg-[#F2F8F7] px-4 py-3 text-xs text-[#12302C]">
          Your demo: <strong>{formatDemo(current)}</strong> (Addis Ababa time)
        </p>
      )}
      <div>
        <div className="mb-2 grid grid-cols-5 gap-1.5 text-center text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          {WEEKDAYS.map((name) => (
            <span key={name}>{name}</span>
          ))}
        </div>
        <div className="space-y-1.5" role="group" aria-label="Demo days">
          {weeks.map((week, index) => (
            <div key={index} className="grid grid-cols-5 gap-1.5">
              {week.map((cell, column) =>
                cell ? (
                  <button
                    key={cell.date}
                    type="button"
                    disabled={cell.free === 0}
                    aria-pressed={cell.date === shownDay}
                    aria-label={`${dayParts(cell.date).label}, ${cell.free} free`}
                    data-testid="demo-day"
                    data-date={cell.date}
                    onClick={() => {
                      setDay(cell.date);
                      setChosen(null);
                      setError(null);
                    }}
                    className={cn(
                      "flex flex-col items-center rounded-xl border px-1 py-2 text-xs transition-all disabled:cursor-not-allowed disabled:opacity-40",
                      cell.date === shownDay
                        ? "border-[#1E5852] bg-[#1E5852] text-white"
                        : "border-[#E2E8F0] bg-[#F8FAFB] text-[#12302C] hover:border-[#1E5852]/40"
                    )}
                  >
                    <span className="text-base font-semibold leading-none">{dayParts(cell.date).day}</span>
                    <span className={cn("mt-1 text-[10px]", cell.date === shownDay ? "text-white/80" : "text-slate-400")}>
                      {dayParts(cell.date).month}
                    </span>
                  </button>
                ) : (
                  <span key={`empty-${column}`} />
                )
              )}
            </div>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-2 text-xs font-semibold text-[#12302C]">
          {shownDay ? `Times on ${dayParts(shownDay).label}` : "No free times"}{" "}
          <span className="font-normal text-slate-400">(Addis Ababa time, 30 minutes)</span>
        </p>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4" role="radiogroup" aria-label="Demo times">
          {daySlots.map((slot) => {
            const mine = current !== null && new Date(slot).getTime() === new Date(current).getTime();
            return (
              <button
                key={slot}
                type="button"
                role="radio"
                aria-checked={chosen === slot}
                data-testid="demo-slot"
                data-slot={slot}
                disabled={mine}
                onClick={() => {
                  setChosen(slot);
                  setError(null);
                }}
                className={cn(choiceClass(chosen === slot), "py-2.5 text-center", mine && "cursor-default opacity-60")}
              >
                {formatTime(slot)}
                {mine && <span className="block text-[10px] font-normal">yours</span>}
              </button>
            );
          })}
        </div>
      </div>

      <StepError message={error} />
      <div className="flex justify-end">
        <button type="button" className={nextButtonClass} disabled={!chosen || busy} onClick={() => void book()}>
          {busy ? "Booking…" : (confirmLabel ?? (current ? "Move my demo" : "Book this time"))}
        </button>
      </div>
    </div>
  );
}
