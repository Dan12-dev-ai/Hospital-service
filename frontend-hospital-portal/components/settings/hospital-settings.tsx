"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { Icon } from "@/components/ui/icon";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import { useDashboard } from "@/components/dashboard/dashboard-context";
import { RoleGate, FormError, inputClass, labelClass, primaryButtonClass, secondaryButtonClass } from "@/components/common/states";
import { useSession } from "@/components/session/session-context";
import { missingText } from "@/components/session/hospital-status-banner";
import { ApiError, apiFetch } from "@/lib/api";
import { SERVICES, type Hospital, type HospitalKind, type ServiceKey } from "@/lib/api-types";
import { BIRR_PATTERN } from "@/lib/format";

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

/** Checks the form and builds the PATCH body, or returns the first problem. */
export function buildPayload(form: Form): { payload: Payload } | { problem: string } {
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
  const prices: Record<"price_in_person" | "price_video", string | null> = {
    price_in_person: null,
    price_video: null,
  };
  for (const key of ["price_in_person", "price_video"] as const) {
    const value = form[key].trim();
    if (value === "") continue;
    if (!BIRR_PATTERN.test(value) || Number(value) > 1_000_000) {
      return { problem: "Prices are in birr, e.g. 150 or 150.50 (at most 1,000,000)." };
    }
    prices[key] = value;
  }
  if (form.video_enabled && prices.price_video === null) {
    return { problem: "Set a video visit price before turning video visits on." };
  }
  const ahead = form.queue_notify_ahead.trim();
  if (!/^\d{1,2}$/.test(ahead) || Number(ahead) > 20) {
    return { problem: "The queue SMS setting is a number of people from 0 (off) to 20." };
  }
  return {
    payload: {
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
      video_enabled: form.video_enabled,
      // Birr as text: the API takes decimals and stores santim, so no float rounding.
      price_in_person: prices.price_in_person,
      price_video: prices.price_video,
      queue_notify_ahead: Number(ahead),
    },
  };
}

export function HospitalSettings() {
  return (
    <RoleGate roles={["admin"]} what="hospital settings">
      <SettingsLoaded />
    </RoleGate>
  );
}

function SettingsLoaded() {
  const session = useSession();
  if (session.status !== "ready") return null;
  // Keyed by hospital id: a fresh form for a different hospital.
  return <SettingsForm key={session.hospital.id} hospital={session.hospital} />;
}

function SettingsForm({ hospital }: { hospital: Hospital }) {
  const { setHospital } = useSession();
  const { showToast } = useDashboard();
  const [form, setForm] = useState<Form>(() => toForm(hospital));
  const [saved, setSaved] = useState<Hospital>(hospital);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [locating, setLocating] = useState(false);
  const [locationNote, setLocationNote] = useState<string | null>(null);

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function toggleService(key: ServiceKey) {
    setForm((current) => ({
      ...current,
      services: current.services.includes(key)
        ? current.services.filter((s) => s !== key)
        : [...current.services, key],
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
        setLocationNote(
          `Location found (accurate to about ${Math.round(position.coords.accuracy)} m). Check it, then save.`
        );
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
    const built = buildPayload(form);
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
      showToast("Hospital settings saved");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the settings.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-5" data-testid="settings-form">
      <header className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-outline">Administration</p>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Hospital settings</h1>
          <p className="mt-0.5 text-xs text-slate-500">
            What patients see about {saved.name} in the Endod app, and how they can book it.
          </p>
        </div>
        <button type="submit" disabled={busy} className={`${primaryButtonClass} py-2.5`}>
          <Icon name="save" className="text-[18px]" />
          {busy ? "Saving…" : "Save settings"}
        </button>
      </header>

      <ListingStatus hospital={saved} />
      <FormError message={error} />

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
        <Field label="Open hours" htmlFor="h-hours">
          <input id="h-hours" maxLength={80} placeholder="Mon–Sat 8:00–17:00" value={form.open_hours} onChange={(e) => set("open_hours", e.target.value)} className={inputClass} />
        </Field>
        <div className="flex items-end">
          <Toggle id="h-emergency" label="24-hour emergency department" checked={form.emergency} onChange={(value) => set("emergency", value)} />
        </div>
      </Section>

      <Section title="Location" icon="location_on">
        <p className="text-xs text-slate-500 sm:col-span-2">
          Patients find nearby hospitals by this point. Stand at the hospital and use your current location, or enter
          the coordinates (decimal degrees) by hand.
        </p>
        <Field label="Latitude" htmlFor="h-lat">
          <input id="h-lat" inputMode="decimal" placeholder="9.0320" value={form.latitude} onChange={(e) => set("latitude", e.target.value)} className={inputClass} />
        </Field>
        <Field label="Longitude" htmlFor="h-lng">
          <input id="h-lng" inputMode="decimal" placeholder="38.7469" value={form.longitude} onChange={(e) => set("longitude", e.target.value)} className={inputClass} />
        </Field>
        <div className="flex flex-col gap-2 sm:col-span-2 sm:flex-row sm:items-center">
          <button type="button" onClick={fillCurrentLocation} disabled={locating} className={secondaryButtonClass}>
            <Icon name="my_location" className="text-[16px]" />
            {locating ? "Finding location…" : "Use my current location"}
          </button>
          {locationNote && (
            <span data-testid="location-note" className="text-xs text-slate-500">
              {locationNote}
            </span>
          )}
        </div>
      </Section>

      <Section title="Services" icon="medical_services">
        <div className="grid grid-cols-1 gap-2 sm:col-span-2 sm:grid-cols-3">
          {SERVICES.map((service) => (
            <label key={service.key} className="flex cursor-pointer items-center gap-2 rounded-xl bg-surface-container-low px-3 py-2 text-xs font-medium text-on-surface">
              <input
                type="checkbox"
                checked={form.services.includes(service.key)}
                onChange={() => toggleService(service.key)}
                className="h-4 w-4 accent-[#1b6b57]"
              />
              {service.label}
            </label>
          ))}
        </div>
      </Section>

      <Section title="Visits and prices" icon="payments">
        <p className="text-xs text-slate-500 sm:col-span-2">
          Prices are in birr. Patients pay Endod when they book; Endod pays the hospital.
        </p>
        <Field label="In-person visit price (birr)" htmlFor="h-price-in-person">
          <input id="h-price-in-person" inputMode="decimal" placeholder="150.00" value={form.price_in_person} onChange={(e) => set("price_in_person", e.target.value)} className={inputClass} />
        </Field>
        <Field label="Video visit price (birr)" htmlFor="h-price-video">
          <input id="h-price-video" inputMode="decimal" placeholder="120.00" value={form.price_video} onChange={(e) => set("price_video", e.target.value)} className={inputClass} />
        </Field>
        <div className="sm:col-span-2">
          <Toggle id="h-video" label="Offer video visits" checked={form.video_enabled} onChange={(value) => set("video_enabled", value)} />
        </div>
      </Section>

      <Section title="Queue" icon="format_list_numbered">
        <p className="text-xs text-slate-500 sm:col-span-2">
          Patients waiting in a doctor&apos;s queue get a &ldquo;get ready&rdquo; SMS when this many people are ahead of
          them, and another when they are called. 0 turns the &ldquo;get ready&rdquo; SMS off.
        </p>
        <Field label="People ahead for the get-ready SMS" htmlFor="h-queue-ahead">
          <input id="h-queue-ahead" type="number" min={0} max={20} inputMode="numeric" value={form.queue_notify_ahead} onChange={(e) => set("queue_notify_ahead", e.target.value)} className={inputClass} />
        </Field>
      </Section>
    </form>
  );
}

function ListingStatus({ hospital }: { hospital: Hospital }) {
  const status =
    hospital.status === "pending"
      ? { label: "Pending approval by Endod", tone: "bg-amber-50 text-amber-900 border-amber-200" }
      : hospital.status === "suspended"
        ? { label: "Suspended by Endod", tone: "bg-rose-50 text-rose-900 border-rose-200" }
        : hospital.listed
          ? { label: "Listed in the Endod app", tone: "bg-neutral-50 text-neutral-900 border-neutral-200" }
          : { label: "Approved, not listed yet", tone: "bg-sky-50 text-sky-900 border-sky-200" };
  return (
    <section data-testid="listing-status" className={`flex flex-col gap-1 rounded-2xl border px-5 py-3 text-xs ${status.tone}`}>
      <p className="font-bold">
        {status.label} <span className="font-normal opacity-70">• hospital code {hospital.code}</span>
      </p>
      {hospital.missing_for_listing.length > 0 ? (
        <p data-testid="missing-for-listing">
          Still missing before patients can see this hospital: {missingText(hospital)}.
        </p>
      ) : (
        <p data-testid="missing-for-listing">
          Nothing is missing for the listing.
          {hospital.status === "pending" && " Patients will see the hospital once Endod approves it."}
        </p>
      )}
    </section>
  );
}

function Section({ title, icon, children }: { title: string; icon: string; children: ReactNode }) {
  return (
    <section className="rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-bold text-slate-800">
        <Icon name={icon} className="text-[18px] text-black" />
        {title}
      </h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{children}</div>
    </section>
  );
}

function Field({ label, htmlFor, wide, children }: { label: string; htmlFor: string; wide?: boolean; children: ReactNode }) {
  return (
    <div className={wide ? "sm:col-span-2" : undefined}>
      <label htmlFor={htmlFor} className={labelClass}>
        {label}
      </label>
      {children}
    </div>
  );
}

function Toggle({ id, label, checked, onChange }: { id: string; label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label htmlFor={id} className="flex cursor-pointer items-center gap-2 text-xs font-semibold text-on-surface">
      <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 accent-[#1b6b57]" />
      {label}
    </label>
  );
}
