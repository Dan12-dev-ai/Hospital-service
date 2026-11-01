"use client";

import { useState } from "react";
import { Icon } from "@/components/ui/icon";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  DAYS,
  DAY_NAMES,
  DEFAULT_PERIOD,
  formatOpenHours,
  parseOpenHours,
  type Day,
  type OpenHours,
  type Period,
} from "@/lib/open-hours";

/** The first problem with opening hours as text (what the input below gives), or null. */
export function openHoursTextProblem(text: string, required: boolean): string | null {
  if (text.trim() === "") return required ? "Set the opening hours." : null;
  const hours = parseOpenHours(text);
  if (hours === null) {
    return "Set the opening hours: the days, and the opening and closing times (or open 24 hours).";
  }
  for (const [index, period] of hours.periods.entries()) {
    const which = hours.periods.length > 1 ? ` (line ${index + 1})` : "";
    if (period.opens === period.closes) return `Opening hours: the closing time must differ from the opening time${which}.`;
    if (DAYS.indexOf(period.from) > DAYS.indexOf(period.to)) {
      return `Opening hours: the days must run forward, e.g. Monday to Friday${which}.`;
    }
  }
  if (text.length > 80) return "Too many lines of opening hours: combine days, e.g. Monday to Friday.";
  return null;
}

/**
 * Opening hours as days and times (or open 24 hours, every day), instead of
 * free text: gives the text the backend stores, e.g. "Mon-Fri 08:00-17:00, Sat 08:00-12:00".
 */
export function OpenHoursInput({
  id,
  value,
  onChange,
  inputClassName,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  inputClassName: string;
}) {
  // Text saved before the hours were checked (e.g. "100:00") cannot be shown as days and times.
  const [unreadable] = useState(() => (parseOpenHours(value) === null ? value : null));
  const [hours, setHours] = useState<OpenHours>(() => parseOpenHours(value) ?? { alwaysOpen: false, periods: [] });

  function update(next: OpenHours) {
    setHours(next);
    onChange(formatOpenHours(next));
  }

  function setPeriod(index: number, change: Partial<Period>) {
    update({ ...hours, periods: hours.periods.map((p, i) => (i === index ? { ...p, ...change } : p)) });
  }

  function addPeriod() {
    const last = hours.periods[hours.periods.length - 1];
    const next: Period = last ? { from: "Sat", to: "Sat", opens: "08:00", closes: "12:00" } : DEFAULT_PERIOD;
    update({ alwaysOpen: false, periods: [...hours.periods, next] });
  }

  return (
    <div id={id} data-testid="open-hours" className="flex flex-col gap-2">
      {unreadable && (
        <p data-testid="open-hours-unreadable" className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
          The saved opening hours (&ldquo;{unreadable}&rdquo;) are not valid times. Patients still see them until you set them again below.
        </p>
      )}
      <label className="flex cursor-pointer items-center gap-2 text-xs font-semibold text-on-surface">
        <input
          type="checkbox"
          checked={hours.alwaysOpen}
          onChange={(e) =>
            update(e.target.checked ? { alwaysOpen: true, periods: [] } : { alwaysOpen: false, periods: [DEFAULT_PERIOD] })
          }
          className="h-4 w-4 accent-[#1b6b57]"
        />
        Open 24 hours, 7 days a week
      </label>
      {!hours.alwaysOpen && (
        <>
          {hours.periods.length === 0 && <p className="text-xs text-slate-500">No opening hours set yet.</p>}
          {hours.periods.map((period, index) => {
            const suffix = index === 0 ? "" : ` (line ${index + 1})`;
            return (
              <div key={index} data-testid="open-hours-line" className="grid grid-cols-2 items-end gap-2 sm:grid-cols-[1fr_1fr_auto_auto_auto]">
                <DaySelect label={`From${suffix}`} value={period.from} onChange={(from) => setPeriod(index, { from })} />
                <DaySelect label={`To${suffix}`} value={period.to} onChange={(to) => setPeriod(index, { to })} />
                <TimeField label={`Opens at${suffix}`} value={period.opens} onChange={(opens) => setPeriod(index, { opens })} className={inputClassName} />
                <TimeField
                  label={`Closes at${suffix}`}
                  // Midnight closes the day: stored as 24:00, shown as 00:00.
                  value={period.closes === "24:00" ? "00:00" : period.closes}
                  onChange={(closes) => setPeriod(index, { closes: closes === "00:00" ? "24:00" : closes })}
                  className={inputClassName}
                />
                <button
                  type="button"
                  aria-label={`Remove opening hours${suffix || " (line 1)"}`}
                  onClick={() => update({ ...hours, periods: hours.periods.filter((_, i) => i !== index) })}
                  className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100"
                >
                  <Icon name="close" className="text-[18px]" />
                </button>
              </div>
            );
          })}
          <button
            type="button"
            onClick={addPeriod}
            className="inline-flex w-fit items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-black hover:bg-slate-100"
          >
            <Icon name="add" className="text-[16px]" />
            {hours.periods.length === 0 ? "Add opening hours" : "Add other days"}
          </button>
        </>
      )}
    </div>
  );
}

function DaySelect({ label, value, onChange }: { label: string; value: Day; onChange: (day: Day) => void }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-slate-500">{label}</span>
      <Select value={value} onValueChange={(v) => v && onChange(v as Day)}>
        <SelectTrigger aria-label={label} className="h-9 w-full cursor-pointer">
          <SelectValue>{(v) => DAY_NAMES[v as Day] ?? v}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {DAYS.map((day) => (
            <SelectItem key={day} value={day}>
              {DAY_NAMES[day]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function TimeField({
  label,
  value,
  onChange,
  className,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  className: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-slate-500">{label}</span>
      <input
        type="time"
        aria-label={label}
        required
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={className}
      />
    </label>
  );
}
