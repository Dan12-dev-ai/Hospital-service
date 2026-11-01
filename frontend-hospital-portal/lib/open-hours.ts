/**
 * Opening hours as the backend stores them (backend-hospital/app/validation.py,
 * normalize_open_hours) and patients see them in the Endod app: "24/7", or
 * periods such as "Mon-Fri 08:00-17:00, Sat 08:00-12:00" ("Daily" for every day).
 */

export const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;
export type Day = (typeof DAYS)[number];

export const DAY_NAMES: Record<Day, string> = {
  Mon: "Monday",
  Tue: "Tuesday",
  Wed: "Wednesday",
  Thu: "Thursday",
  Fri: "Friday",
  Sat: "Saturday",
  Sun: "Sunday",
};

export const ALWAYS_OPEN = "24/7";

export type Period = { from: Day; to: Day; opens: string; closes: string };
export type OpenHours = { alwaysOpen: boolean; periods: Period[] };

export const DEFAULT_PERIOD: Period = { from: "Mon", to: "Fri", opens: "08:00", closes: "17:00" };

const PERIOD = /^([A-Za-z]+)(?:-([A-Za-z]+))?\s+(\d{2}:\d{2})-(\d{2}:\d{2})$/;
const CLOCK = /^(?:[01]\d|2[0-3]):[0-5]\d$|^24:00$/;

function isDay(value: string): value is Day {
  return (DAYS as readonly string[]).includes(value);
}

/** The stored text as a form, or null when it is not in the stored form (e.g. typed before it was checked). */
export function parseOpenHours(text: string | null | undefined): OpenHours | null {
  const value = (text ?? "").trim();
  if (value === "") return { alwaysOpen: false, periods: [] };
  if (value === ALWAYS_OPEN) return { alwaysOpen: true, periods: [] };
  const periods: Period[] = [];
  for (const part of value.split(/\s*,\s*/)) {
    const match = PERIOD.exec(part);
    if (!match) return null;
    const [, first, last, opens, closes] = match;
    let from: Day;
    let to: Day;
    if (first === "Daily" && !last) {
      from = "Mon";
      to = "Sun";
    } else if (isDay(first) && (!last || isDay(last))) {
      from = first;
      to = (last as Day | undefined) ?? first;
    } else {
      return null;
    }
    if (!CLOCK.test(opens) || !CLOCK.test(closes)) return null;
    periods.push({ from, to, opens, closes });
  }
  return { alwaysOpen: false, periods };
}

function daysLabel(period: Period): string {
  if (period.from === "Mon" && period.to === "Sun") return "Daily";
  return period.from === period.to ? period.from : `${period.from}-${period.to}`;
}

/** The text to save (the stored form), or "" for none. */
export function formatOpenHours(hours: OpenHours): string {
  if (hours.alwaysOpen) return ALWAYS_OPEN;
  return hours.periods.map((p) => `${daysLabel(p)} ${p.opens}-${p.closes}`).join(", ");
}
