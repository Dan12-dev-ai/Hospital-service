/** Small display helpers shared by the portal's pages. */

export function initialsOf(name: string): string {
  const parts = name.replace(/^(dr\.?|ዶ\/ር)\s+/i, "").split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

export const DEFAULT_TIMEZONE = "Africa/Addis_Ababa";

/** "Tue 21 Oct, 9:30 AM" in the hospital's own time zone. */
export function formatDateTime(iso: string, timeZone = DEFAULT_TIMEZONE): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone,
  }).format(date);
}

/** "150.00" (birr text from the API) -> "ETB 150.00". */
export function formatBirr(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  return `ETB ${amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** A birr amount as typed: digits with up to two decimals. */
export const BIRR_PATTERN = /^\d{1,7}(\.\d{1,2})?$/;

export function titleCase(value: string): string {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
