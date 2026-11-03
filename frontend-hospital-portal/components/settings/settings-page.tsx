"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Icon } from "@/components/ui/icon";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useToast } from "@/components/shell/toast";
import { PageHeader } from "@/components/shell/dashboard-shell";
import {
  ErrorState,
  FormError,
  LoadingState,
  RoleGate,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { useSession } from "@/components/session/session-context";
import { OpenHoursInput, openHoursTextProblem } from "@/components/common/open-hours-input";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import {
  MISSING_LABELS,
  SERVICES,
  type Hospital,
  type HospitalKind,
  type PriceItem,
  type PriceList,
  type ServiceKey,
} from "@/lib/api-types";
import { BIRR_PATTERN, formatBirr } from "@/lib/format";

type Form = {
  name: string;
  name_am: string;
  kind: HospitalKind;
  city: string;
  address: string;
  phone: string;
  ambulance_phone: string;
  emergency: boolean;
  latitude: string;
  longitude: string;
  services: ServiceKey[];
  open_hours: string;
  video_enabled: boolean;
  price_in_person: string;
  price_video: string;
  queue_notify_ahead: string;
};

export function missingText(hospital: Hospital): string {
  return hospital.missing_for_listing.map((key) => MISSING_LABELS[key] ?? key.replace(/_/g, " ")).join(" and ");
}

function toForm(h: Hospital): Form {
  return {
    name: h.name,
    name_am: h.name_am ?? "",
    kind: h.kind,
    city: h.city ?? "",
    address: h.address ?? "",
    phone: h.phone ?? "",
    ambulance_phone: h.ambulance_phone ?? "",
    emergency: h.emergency,
    latitude: h.latitude === null ? "" : String(h.latitude),
    longitude: h.longitude === null ? "" : String(h.longitude),
    services: [...h.services],
    open_hours: h.open_hours ?? "",
    video_enabled: h.video_enabled,
    price_in_person: h.price_in_person ?? "",
    price_video: h.price_video ?? "",
    queue_notify_ahead: String(h.queue_notify_ahead ?? 3),
  };
}

type Payload = Record<string, string | number | boolean | string[] | null>;

/**
 * Checks the form and builds the PATCH body, or returns the first problem.
 * Video visits are sent only while Endod offers them (`video`).
 */
export function buildPayload(form: Form, savedHours: string | null = null, video = false): { payload: Payload } | { problem: string } {
  if (form.name.trim().length < 2) return { problem: "Enter the hospital's name." };
  const lat = form.latitude.trim();
  const lng = form.longitude.trim();
  if ((lat === "") !== (lng === "")) return { problem: "Give both latitude and longitude, or neither." };
  let latitude: number | null = null;
  let longitude: number | null = null;
  if (lat !== "") {
    latitude = Number(lat);
    longitude = Number(lng);
    if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90) {
      return { problem: "Latitude must be a number between -90 and 90." };
    }
    if (!Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
      return { problem: "Longitude must be a number between -180 and 180." };
    }
  }
  const prices: Record<"price_in_person" | "price_video", string | null> = { price_in_person: null, price_video: null };
  for (const key of ["price_in_person", "price_video"] as const) {
    const value = form[key].trim();
    if (value === "") continue;
    if (!BIRR_PATTERN.test(value) || Number(value) > 1_000_000) {
      return { problem: "Prices are in birr, e.g. 150 or 150.50 (at most 1,000,000)." };
    }
    prices[key] = value;
  }
  if (video && form.video_enabled && prices.price_video === null) {
    return { problem: "Set a video visit price before turning video visits on." };
  }
  // Hours saved before they were checked (e.g. "100:00") and left as they are
  // are not sent: they do not block saving the other settings.
  const hoursUnchanged = savedHours !== null && form.open_hours === savedHours;
  const hoursProblem = hoursUnchanged ? null : openHoursTextProblem(form.open_hours, false);
  if (hoursProblem) return { problem: hoursProblem };
  const ahead = form.queue_notify_ahead.trim();
  if (!/^\d{1,2}$/.test(ahead) || Number(ahead) > 20) {
    return { problem: "The queue SMS setting is a number of people from 0 (off) to 20." };
  }
  const payload: Payload = {
    name: form.name.trim(),
    name_am: form.name_am.trim() || null,
    kind: form.kind,
    city: form.city.trim() || null,
    address: form.address.trim() || null,
    phone: form.phone.trim() || null,
    ambulance_phone: form.ambulance_phone.trim() || null,
    emergency: form.emergency,
    latitude,
    longitude,
    services: form.services,
    open_hours: form.open_hours.trim() || null,
    // Birr as text: the API takes decimals and stores santim, so no float rounding.
    price_in_person: prices.price_in_person,
    queue_notify_ahead: Number(ahead),
  };
  if (video) {
    payload.video_enabled = form.video_enabled;
    payload.price_video = prices.price_video;
  }
  if (hoursUnchanged) delete payload.open_hours;
  return { payload };
}

/**
 * Settings: the hospital's listing in the Endod app (contact, hours,
 * services, location, the in-person consultation price) and the price list
 * its system synced. Administrators change them; developers read them.
 */
export function SettingsPage() {
  return (
    <RoleGate roles={["admin", "developer"]} what="hospital settings">
      <SettingsLoaded />
      <PriceListSection />
    </RoleGate>
  );
}

function SettingsLoaded() {
  const session = useSession();
  if (session.status !== "ready") return null;
  // Keyed by hospital id: a fresh form for a different hospital.
  return <SettingsForm key={session.hospital.id} hospital={session.hospital} canEdit={session.staff.role === "admin"} />;
}

function SettingsForm({ hospital, canEdit }: { hospital: Hospital; canEdit: boolean }) {
  const { setHospital } = useSession();
  const toast = useToast();
  const [form, setForm] = useState<Form>(() => toForm(hospital));
  const [saved, setSaved] = useState<Hospital>(hospital);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [locating, setLocating] = useState(false);
  const [locationNote, setLocationNote] = useState<string | null>(null);
  // Video visits: only while Endod offers them (HOSPITAL_VIDEO_VISITS_ENABLED, off by default).
  const video = Boolean(saved.video_visits_offered);

  // /settings?focus=price_in_person (or location): from the Overview checklist.
  useEffect(() => {
    const focus = new URLSearchParams(window.location.search).get("focus");
    const field = focus ? FOCUS_TARGETS[focus] : undefined;
    const element = field ? document.getElementById(field) : null;
    if (element) {
      element.scrollIntoView({ block: "center" });
      element.focus({ preventScroll: true });
    }
  }, []);

  const missing = new Set(saved.status === "approved" ? saved.missing_for_listing : []);

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function toggleService(key: ServiceKey) {
    setForm((current) => ({
      ...current,
      services: current.services.includes(key) ? current.services.filter((s) => s !== key) : [...current.services, key],
    }));
  }

  function fillCurrentLocation() {
    if (!("geolocation" in navigator)) {
      setLocationNote("This browser cannot share its location. Enter the coordinates by hand.");
      return;
    }
    setLocating(true);
    setLocationNote(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocating(false);
        setForm((current) => ({
          ...current,
          latitude: position.coords.latitude.toFixed(6),
          longitude: position.coords.longitude.toFixed(6),
        }));
        setLocationNote(`Location found (accurate to about ${Math.round(position.coords.accuracy)} m). Check it, then save.`);
      },
      (geoError) => {
        setLocating(false);
        setLocationNote(
          geoError.code === geoError.PERMISSION_DENIED
            ? "Location permission was refused. Enter the coordinates by hand."
            : "Could not find your location. Enter the coordinates by hand."
        );
      },
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 0 }
    );
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const built = buildPayload(form, saved.open_hours, video);
    if ("problem" in built) {
      setError(built.problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await apiFetch<Hospital>("hospital", { method: "PATCH", body: built.payload });
      setSaved(updated);
      setForm(toForm(updated));
      setHospital(updated);
      toast("Hospital settings saved");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the settings.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-6" data-testid="settings-form">
      <PageHeader
        title="Settings"
        description={`What patients see about ${saved.name} in the Endod app, and how they book it.`}
        actions={
          canEdit ? (
            <button type="submit" disabled={busy} className={primaryButtonClass}>
              <Icon name="save" className="text-[16px]" />
              {busy ? "Saving…" : "Save settings"}
            </button>
          ) : undefined
        }
      />
      <ListingStatus hospital={saved} />
      {!canEdit && (
        <p data-testid="read-only-note" className="text-xs text-neutral-500">
          Only administrators change these settings.
        </p>
      )}
      <FormError message={error} />

      <fieldset disabled={!canEdit} className="flex min-w-0 flex-col gap-6">
        <Section title="Hospital" icon="domain">
          <Field label="Name" htmlFor="h-name" wide>
            <input id="h-name" maxLength={160} value={form.name} onChange={(e) => set("name", e.target.value)} className={inputClass} />
          </Field>
          <Field label="Name in Amharic" htmlFor="h-name-am" wide>
            <input id="h-name-am" maxLength={160} value={form.name_am} onChange={(e) => set("name_am", e.target.value)} className={inputClass} />
          </Field>
          <Field label="Kind" htmlFor="h-kind">
            <Select value={form.kind} onValueChange={(v) => set("kind", (v ?? form.kind) as HospitalKind)}>
              <SelectTrigger id="h-kind" className="w-full cursor-pointer">
                <SelectValue>{(v) => (v === "public" ? "Public" : v === "private" ? "Private" : v)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="public">Public</SelectItem>
                <SelectItem value="private">Private</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="City" htmlFor="h-city">
            <input id="h-city" maxLength={100} value={form.city} onChange={(e) => set("city", e.target.value)} className={inputClass} />
          </Field>
          <Field label="Address" htmlFor="h-address" wide>
            <input id="h-address" maxLength={200} value={form.address} onChange={(e) => set("address", e.target.value)} className={inputClass} />
          </Field>
          <Field label="Phone" htmlFor="h-phone">
            <input id="h-phone" type="tel" placeholder="011 551 7611" value={form.phone} onChange={(e) => set("phone", e.target.value)} className={inputClass} />
          </Field>
          <Field label="Ambulance phone" htmlFor="h-ambulance">
            <input id="h-ambulance" type="tel" placeholder="907" value={form.ambulance_phone} onChange={(e) => set("ambulance_phone", e.target.value)} className={inputClass} />
          </Field>
          <div className="sm:col-span-2">
            <Toggle id="h-emergency" label="24-hour emergency department" checked={form.emergency} onChange={(value) => set("emergency", value)} />
          </div>
          <fieldset className="sm:col-span-2">
            <legend className={labelClass}>Open hours</legend>
            <OpenHoursInput id="h-hours" value={form.open_hours} onChange={(value) => set("open_hours", value)} inputClassName={inputClass} />
          </fieldset>
        </Section>

        <Section title="Location" icon="location_on" needed={missing.has("location")}>
          <p className="text-xs text-neutral-500 sm:col-span-2">
            Patients find nearby hospitals by this point. Stand at the hospital and use your current location, or enter
            the coordinates (decimal degrees) by hand.
          </p>
          <Field label="Latitude" htmlFor="h-lat" needed={missing.has("location")}>
            <input id="h-lat" inputMode="decimal" placeholder="9.0320" value={form.latitude} onChange={(e) => set("latitude", e.target.value)} className={inputClass} />
          </Field>
          <Field label="Longitude" htmlFor="h-lng" needed={missing.has("location")}>
            <input id="h-lng" inputMode="decimal" placeholder="38.7469" value={form.longitude} onChange={(e) => set("longitude", e.target.value)} className={inputClass} />
          </Field>
          <div className="flex flex-col gap-2 sm:col-span-2 sm:flex-row sm:items-center">
            <button type="button" onClick={fillCurrentLocation} disabled={locating} className={secondaryButtonClass}>
              <Icon name="my_location" className="text-[16px]" />
              {locating ? "Finding location…" : "Use my current location"}
            </button>
            {locationNote && (
              <span data-testid="location-note" className="text-xs text-neutral-500">
                {locationNote}
              </span>
            )}
          </div>
        </Section>

        <Section title="Services" icon="medical_services">
          <div className="grid grid-cols-1 gap-2 sm:col-span-2 sm:grid-cols-3">
            {SERVICES.map((service) => (
              <label
                key={service.key}
                className="flex cursor-pointer items-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-xs font-medium text-neutral-800"
              >
                <input
                  type="checkbox"
                  checked={form.services.includes(service.key)}
                  onChange={() => toggleService(service.key)}
                  className="h-4 w-4 accent-neutral-900"
                />
                {service.label}
              </label>
            ))}
          </div>
        </Section>

        <Section title="Consultation price" icon="payments" needed={missing.has("price_in_person")}>
          <p className="text-xs text-neutral-500 sm:col-span-2">
            The in-person visit price patients see when they book, in birr (<strong>0 is allowed</strong> for free
            visits). Your system can also set it with <code className="font-mono">PUT /prices/consultation</code>.
          </p>
          <Field label="In-person visit price (birr)" htmlFor="h-price-in-person" needed={missing.has("price_in_person")}>
            <input
              id="h-price-in-person"
              inputMode="decimal"
              placeholder="150.00"
              value={form.price_in_person}
              onChange={(e) => set("price_in_person", e.target.value)}
              className={inputClass}
            />
          </Field>
          {video && (
            <>
              <Field label="Video visit price (birr)" htmlFor="h-price-video">
                <input id="h-price-video" inputMode="decimal" placeholder="120.00" value={form.price_video} onChange={(e) => set("price_video", e.target.value)} className={inputClass} />
              </Field>
              <div className="sm:col-span-2">
                <Toggle id="h-video" label="Offer video visits" checked={form.video_enabled} onChange={(value) => set("video_enabled", value)} />
              </div>
            </>
          )}
        </Section>

        <Section title="Queue" icon="format_list_numbered">
          <p className="text-xs text-neutral-500 sm:col-span-2">
            Patients waiting in a doctor&apos;s queue (run through the API) get a &ldquo;get ready&rdquo; SMS when this
            many people are ahead of them, and another when they are called. 0 turns the &ldquo;get ready&rdquo; SMS off.
          </p>
          <Field label="People ahead for the get-ready SMS" htmlFor="h-queue-ahead">
            <input
              id="h-queue-ahead"
              type="number"
              min={0}
              max={20}
              inputMode="numeric"
              value={form.queue_notify_ahead}
              onChange={(e) => set("queue_notify_ahead", e.target.value)}
              className={inputClass}
            />
          </Field>
        </Section>
      </fieldset>
    </form>
  );
}

/** The settings field each missing listing item is filled in (/settings?focus=...). */
const FOCUS_TARGETS: Record<string, string> = { price_in_person: "h-price-in-person", location: "h-lat" };

function missingLabel(key: string): string {
  const text = MISSING_LABELS[key] ?? key.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function ListingStatus({ hospital }: { hospital: Hospital }) {
  const unlisted = hospital.status === "approved" && !hospital.listed;
  const status =
    hospital.status === "pending"
      ? { label: "Pending approval by Endod", tone: "border bg-amber-50 text-amber-900 border-amber-200" }
      : hospital.status === "suspended"
        ? { label: "Suspended by Endod", tone: "border bg-rose-50 text-rose-900 border-rose-200" }
        : hospital.listed
          ? { label: "Listed in the Endod app", tone: "border bg-neutral-50 text-neutral-900 border-neutral-200" }
          : { label: "Approved, not listed yet", tone: "border-2 border-amber-400 bg-amber-50 text-amber-950" };
  return (
    <section data-testid="listing-status" className={`flex flex-col gap-2 rounded-lg px-5 py-4 text-sm ${status.tone}`}>
      <p className="font-semibold">
        {status.label} <span className="font-normal opacity-70">· hospital code {hospital.code}</span>
      </p>
      {unlisted && (
        <p data-testid="listing-explainer">
          Patients can&apos;t find {hospital.name} in the Endod app until <strong>{missingText(hospital)}</strong> is set.
        </p>
      )}
      {hospital.missing_for_listing.length > 0 ? (
        <div data-testid="missing-for-listing">
          <p className="text-xs font-semibold">Still missing before patients can see this hospital:</p>
          <ul className="mt-1 flex flex-col gap-1">
            {hospital.missing_for_listing.map((key) => (
              <li key={key} className="flex items-center gap-2 text-xs">
                <Icon name="warning" className="text-[14px] text-amber-600" />
                {FOCUS_TARGETS[key] ? (
                  <a href={`#${FOCUS_TARGETS[key]}`} className="font-semibold underline">
                    {missingLabel(key)}
                  </a>
                ) : (
                  missingLabel(key)
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p data-testid="missing-for-listing" className="text-xs">
          Nothing is missing for the listing.
        </p>
      )}
    </section>
  );
}

function Section({ title, icon, needed, children }: { title: string; icon: string; needed?: boolean; children: ReactNode }) {
  return (
    <section
      data-needed={needed ? "true" : undefined}
      className={`rounded-lg bg-white p-5 ${needed ? "border-2 border-amber-400" : "border border-neutral-200"}`}
    >
      <h2 className="mb-4 flex flex-wrap items-center gap-2 text-sm font-semibold text-neutral-900">
        <Icon name={icon} className="text-[16px] text-neutral-500" />
        {title}
        {needed && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-900">
            Needed before patients can see you
          </span>
        )}
      </h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{children}</div>
    </section>
  );
}

function Field({ label, htmlFor, wide, needed, children }: { label: string; htmlFor: string; wide?: boolean; needed?: boolean; children: ReactNode }) {
  return (
    <div data-needed={needed ? "true" : undefined} className={`${wide ? "sm:col-span-2" : ""} ${needed ? "rounded-md bg-amber-50 p-2 ring-2 ring-amber-400" : ""}`}>
      <label htmlFor={htmlFor} className={labelClass}>
        {label}
      </label>
      {needed && <p className="mb-1 text-[11px] font-semibold text-amber-800">Required before patients can see you</p>}
      {children}
    </div>
  );
}

function Toggle({ id, label, checked, onChange }: { id: string; label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label htmlFor={id} className="flex cursor-pointer items-center gap-2 text-xs font-medium text-neutral-800">
      <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 accent-neutral-900" />
      {label}
    </label>
  );
}

const CATEGORIES: { key: "lab_tests" | "imaging" | "procedures"; title: string; path: string }[] = [
  { key: "lab_tests", title: "Lab tests", path: "PUT /prices/lab-tests" },
  { key: "imaging", title: "Imaging", path: "PUT /prices/imaging" },
  { key: "procedures", title: "Procedures", path: "PUT /prices/procedures" },
];

/** The price list the hospital's system synced through the API (read-only here). */
function PriceListSection() {
  const { data, error, loading, reload } = useApi<PriceList>("prices");
  return (
    <section data-testid="price-list" className="mt-12">
      <h2 className="text-lg font-semibold tracking-tight text-neutral-900">Price list</h2>
      <p className="mt-1 max-w-2xl text-sm text-neutral-500">
        Synced from your system through the API, category by category. Read-only here: change it in your system and
        sync again.
      </p>
      {loading && !data && <LoadingState className="mt-4 shadow-none" />}
      {error && <ErrorState message={error.message} onRetry={reload} className="mt-4" />}
      {data && (
        <div className="mt-4 flex flex-col gap-6">
          <div className="flex items-baseline justify-between rounded-lg border border-neutral-200 px-5 py-3 text-sm">
            <span className="text-neutral-600">Consultation (in person)</span>
            <span data-testid="consultation-price" className="font-medium text-neutral-900">
              {formatBirr(data.consultation.in_person)}
            </span>
          </div>
          {CATEGORIES.map((category) => (
            <PriceTable key={category.key} testId={`prices-${category.key}`} title={category.title} path={category.path} items={data[category.key]} />
          ))}
        </div>
      )}
    </section>
  );
}

function PriceTable({ title, path, items, testId }: { title: string; path: string; items: PriceItem[]; testId: string }) {
  return (
    <div className="rounded-lg border border-neutral-200" data-testid={testId}>
      <div className="flex items-baseline justify-between border-b border-neutral-200 px-5 py-3">
        <h3 className="text-sm font-semibold text-neutral-900">{title}</h3>
        <code className="font-mono text-[11px] text-neutral-500">{path}</code>
      </div>
      {items.length === 0 ? (
        <p className="px-5 py-4 text-xs text-neutral-500">Nothing synced yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-neutral-500">
              <tr>
                <th className="px-5 py-2 font-medium">Code</th>
                <th className="px-5 py-2 font-medium">Name</th>
                <th className="px-5 py-2 text-right font-medium">Price</th>
                <th className="px-5 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.code} className="border-t border-neutral-100">
                  <td className="px-5 py-2 font-mono text-xs">{item.code}</td>
                  <td className="px-5 py-2">{item.name}</td>
                  <td className="px-5 py-2 text-right tabular-nums">{formatBirr(item.price)}</td>
                  <td className="px-5 py-2 text-xs text-neutral-500">{item.active ? "Offered" : "Not offered now"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
