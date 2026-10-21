"use client";

import { useRef, useState, type FormEvent, type ReactNode } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { Icon } from "@/components/ui/icon";
import { ApiError, apiFetch, apiUpload, fileUrl } from "@/lib/api";
import { SERVICES, type FacilityType, type HospitalKind, type ServiceKey } from "@/lib/api-types";
import { passwordProblem } from "@/lib/password";
import {
  formatDemo,
  formatSize,
  type Application,
  type ApplicationDocument,
} from "@/lib/onboarding-types";
import {
  StepError,
  choiceClass,
  fieldClass,
  fieldLabelClass,
  nextButtonClass,
  softButtonClass,
  stepHeadingClass,
} from "@/components/onboarding/onboarding-frame";
import { DemoPicker } from "@/components/onboarding/demo-picker";
import type { Point } from "@/components/onboarding/location-map";

// Leaflet touches `window` as it loads: the map is rendered in the browser only.
const LocationMap = dynamic(() => import("@/components/onboarding/location-map").then((m) => m.LocationMap), {
  ssr: false,
  loading: () => <div className="h-64 w-full animate-pulse rounded-2xl bg-slate-100 sm:h-72" />,
});

function message(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function StepHeading({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="mb-5">
      <h2 className={stepHeadingClass}>{title}</h2>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

/** Back on the left, the step's action on the right (as in the patient app). */
export function StepNav({
  onBack,
  next,
  busy,
  disabled,
  nextLabel = "Continue",
}: {
  onBack?: () => void;
  next?: boolean;
  busy?: boolean;
  disabled?: boolean;
  nextLabel?: string;
}) {
  return (
    <div className="mt-7 flex items-center justify-between gap-3">
      <button
        type="button"
        onClick={onBack}
        disabled={!onBack}
        className={`rounded-full px-5 py-3 text-sm font-medium text-slate-500 transition-colors hover:text-[#12302C] ${onBack ? "" : "invisible"}`}
      >
        Back
      </button>
      {next !== false && (
        <button type="submit" className={nextButtonClass} disabled={busy || disabled}>
          {busy ? "Saving…" : nextLabel}
        </button>
      )}
    </div>
  );
}

function Field({ id, label, hint, children }: { id: string; label: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className={fieldLabelClass}>
        {label}
      </label>
      {children}
      {hint && <p className="mt-1 text-[11px] text-slate-400">{hint}</p>}
    </div>
  );
}

function Choices<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string; hint?: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <fieldset>
      <legend className={fieldLabelClass}>{label}</legend>
      <div className="grid grid-cols-2 gap-2.5" role="radiogroup" aria-label={label}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={value === option.value}
            onClick={() => onChange(option.value)}
            className={`${choiceClass(value === option.value)} text-left`}
          >
            <span className="block">{option.label}</span>
            {option.hint && <span className="mt-0.5 block text-[11px] font-normal text-slate-400">{option.hint}</span>}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

const FACILITY_TYPES: { value: FacilityType; label: string; hint: string }[] = [
  { value: "hospital", label: "Hospital", hint: "In-patient wards and departments" },
  { value: "clinic", label: "Clinic", hint: "Out-patient care" },
];

// --- 1. the account (signed out) or the contact person (signed in) ---------------------

export function AccountStep({ onCreated }: { onCreated: () => void }) {
  const [form, setForm] = useState({
    hospital_name: "",
    facility_type: "hospital" as FacilityType,
    admin_name: "",
    admin_title: "",
    admin_phone: "",
    admin_email: "",
    password: "",
    confirm: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.hospital_name.trim() || !form.admin_name.trim() || !form.admin_title.trim() || !form.admin_phone.trim()) {
      return setError("Fill in the facility's name and your name, role and mobile number.");
    }
    const problem = passwordProblem(form.password);
    if (problem) return setError(problem);
    if (form.password !== form.confirm) return setError("The two passwords do not match.");
    setBusy(true);
    setError(null);
    try {
      await apiFetch("onboarding", {
        method: "POST",
        redirectOn401: false,
        body: {
          hospital_name: form.hospital_name.trim(),
          facility_type: form.facility_type,
          admin_name: form.admin_name.trim(),
          admin_title: form.admin_title.trim(),
          admin_phone: form.admin_phone.trim(),
          admin_email: form.admin_email.trim(),
          password: form.password,
        },
      });
      onCreated();
    } catch (err) {
      setError(message(err, "Your account could not be created."));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate data-testid="step-account">
      <StepHeading
        title="Let's get you started"
        hint="Tell us your facility's name and who we should talk to. This creates your account: you can stop at any step and continue later by signing in."
      />
      <div className="space-y-4">
        <Choices label="Facility type" value={form.facility_type} options={FACILITY_TYPES} onChange={(v) => set("facility_type", v)} />
        <Field id="account-facility-name" label="Facility name">
          <input id="account-facility-name" className={fieldClass} maxLength={160} value={form.hospital_name} onChange={(e) => set("hospital_name", e.target.value)} />
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field id="account-name" label="Your full name">
            <input id="account-name" className={fieldClass} autoComplete="name" maxLength={120} value={form.admin_name} onChange={(e) => set("admin_name", e.target.value)} />
          </Field>
          <Field id="account-title" label="Your role or title">
            <input id="account-title" className={fieldClass} maxLength={80} placeholder="Medical Director" value={form.admin_title} onChange={(e) => set("admin_title", e.target.value)} />
          </Field>
          <Field id="account-phone" label="Your mobile number" hint="Endod texts your demo confirmation here.">
            <input id="account-phone" className={fieldClass} type="tel" inputMode="tel" autoComplete="tel" placeholder="0911 234 567" value={form.admin_phone} onChange={(e) => set("admin_phone", e.target.value)} />
          </Field>
          <Field id="account-email" label="Work email">
            <input id="account-email" className={fieldClass} type="email" autoComplete="username" value={form.admin_email} onChange={(e) => set("admin_email", e.target.value)} />
          </Field>
          <Field id="account-password" label="Password" hint="At least 10 characters, with upper and lower case letters.">
            <input id="account-password" className={fieldClass} type="password" autoComplete="new-password" value={form.password} onChange={(e) => set("password", e.target.value)} />
          </Field>
          <Field id="account-confirm" label="Confirm password">
            <input id="account-confirm" className={fieldClass} type="password" autoComplete="new-password" value={form.confirm} onChange={(e) => set("confirm", e.target.value)} />
          </Field>
        </div>
      </div>
      <StepError message={error} />
      <StepNav busy={busy} nextLabel="Create account" disabled={!form.admin_email || !form.password} />
      <p className="mt-2 text-center text-xs text-slate-500">
        Already started?{" "}
        <Link href="/login?next=%2Fonboarding" className="font-semibold text-[#1E5852] hover:underline">
          Sign in to continue
        </Link>
      </p>
    </form>
  );
}

type StepProps = {
  application: Application;
  onSaved: (application: Application) => void;
  onBack?: () => void;
};

export function ContactStep({ application, onSaved, onBack }: StepProps) {
  const [form, setForm] = useState({
    full_name: application.contact.full_name ?? "",
    title: application.contact.title ?? "",
    phone: application.contact.phone ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSaved(await apiFetch<Application>("onboarding/contact", { method: "PATCH", body: form }));
    } catch (err) {
      setError(message(err, "Could not save."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate data-testid="step-contact">
      <StepHeading title="Contact person" hint="Endod contacts this person about the application and the demo." />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field id="contact-name" label="Full name">
          <input id="contact-name" className={fieldClass} maxLength={120} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
        </Field>
        <Field id="contact-title" label="Role or title">
          <input id="contact-title" className={fieldClass} maxLength={80} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </Field>
        <Field id="contact-phone" label="Mobile number" hint="Endod texts your demo confirmation here.">
          <input id="contact-phone" className={fieldClass} type="tel" inputMode="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
        </Field>
        <Field id="contact-email" label="Email (your sign-in)">
          <input id="contact-email" className={fieldClass} value={application.contact.email ?? ""} disabled readOnly />
        </Field>
      </div>
      <StepError message={error} />
      <StepNav onBack={onBack} busy={busy} />
    </form>
  );
}

// --- 2. the facility -----------------------------------------------------------------------

export function FacilityStep({ application, onSaved, onBack }: StepProps) {
  const f = application.facility;
  const [form, setForm] = useState({
    facility_type: f.facility_type,
    ownership: f.ownership,
    name: f.name ?? "",
    name_am: f.name_am ?? "",
    city: f.city ?? "",
    phone: f.phone ?? "",
    services: f.services,
    open_hours: f.open_hours ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function toggle(service: ServiceKey) {
    setForm((current) => ({
      ...current,
      services: current.services.includes(service)
        ? current.services.filter((s) => s !== service)
        : [...current.services, service],
    }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.name.trim() || !form.city.trim() || !form.phone.trim() || !form.open_hours.trim()) {
      return setError("Fill in the name, city, phone and opening hours.");
    }
    if (form.services.length === 0) return setError("Choose at least one service.");
    setBusy(true);
    setError(null);
    try {
      onSaved(
        await apiFetch<Application>("onboarding/facility", {
          method: "PATCH",
          body: { ...form, name: form.name.trim(), name_am: form.name_am.trim() || null, city: form.city.trim() },
        })
      );
    } catch (err) {
      setError(message(err, "Could not save."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate data-testid="step-facility">
      <StepHeading title="Your facility" hint="What patients will see in the Endod app once you are approved." />
      <div className="space-y-4">
        <Choices label="Facility type" value={form.facility_type} options={FACILITY_TYPES} onChange={(v) => setForm({ ...form, facility_type: v })} />
        <Choices<HospitalKind>
          label="Ownership"
          value={form.ownership}
          options={[
            { value: "private", label: "Private" },
            { value: "public", label: "Public" },
          ]}
          onChange={(v) => setForm({ ...form, ownership: v })}
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field id="facility-name" label="Name">
            <input id="facility-name" className={fieldClass} maxLength={160} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field id="facility-name-am" label="Name in Amharic (optional)">
            <input id="facility-name-am" className={fieldClass} maxLength={160} value={form.name_am} onChange={(e) => setForm({ ...form, name_am: e.target.value })} />
          </Field>
          <Field id="facility-city" label="City">
            <input id="facility-city" className={fieldClass} maxLength={100} value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
          </Field>
          <Field id="facility-phone" label="Facility phone">
            <input id="facility-phone" className={fieldClass} type="tel" placeholder="011 551 7611" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          </Field>
        </div>
        <fieldset>
          <legend className={fieldLabelClass}>Services</legend>
          <div className="grid grid-cols-2 gap-2" role="group" aria-label="Services">
            {SERVICES.map((service) => {
              const selected = form.services.includes(service.key);
              return (
                <label key={service.key} className={`${choiceClass(selected)} flex items-center gap-2.5 py-2.5`}>
                  <input type="checkbox" className="h-4 w-4 accent-[#1E5852]" checked={selected} onChange={() => toggle(service.key)} />
                  <span>{service.label}</span>
                </label>
              );
            })}
          </div>
        </fieldset>
        <Field id="facility-hours" label="Opening hours" hint="For example: Mon–Sat 08:00–17:00, emergency 24/7">
          <input id="facility-hours" className={fieldClass} maxLength={80} value={form.open_hours} onChange={(e) => setForm({ ...form, open_hours: e.target.value })} />
        </Field>
      </div>
      <StepError message={error} />
      <StepNav onBack={onBack} busy={busy} />
    </form>
  );
}

// --- 3. the location -------------------------------------------------------------------------

export function LocationStep({ application, onSaved, onBack }: StepProps) {
  const l = application.location;
  const [address, setAddress] = useState(l.address ?? "");
  const [latitude, setLatitude] = useState(l.latitude?.toFixed(6) ?? "");
  const [longitude, setLongitude] = useState(l.longitude?.toFixed(6) ?? "");
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const lat = Number(latitude);
  const lng = Number(longitude);
  const point: Point | null =
    latitude.trim() && longitude.trim() && Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180
      ? { latitude: lat, longitude: lng }
      : null;

  function place(next: Point) {
    setLatitude(next.latitude.toFixed(6));
    setLongitude(next.longitude.toFixed(6));
  }

  function locate() {
    if (!("geolocation" in navigator)) return setNote("This browser cannot find your location; drag the pin instead.");
    setNote("Finding your location…");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        place({ latitude: position.coords.latitude, longitude: position.coords.longitude });
        setNote("Location found. Drag the pin if it is not exactly at your entrance.");
      },
      () => setNote("Your location could not be found; drag the pin instead."),
      { enableHighAccuracy: true, timeout: 10_000 }
    );
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!address.trim()) return setError("Enter the address.");
    if (!point) return setError("Place the pin on the map, or enter the latitude and longitude.");
    setBusy(true);
    setError(null);
    try {
      onSaved(
        await apiFetch<Application>("onboarding/location", {
          method: "PATCH",
          body: { address: address.trim(), latitude: point.latitude, longitude: point.longitude },
        })
      );
    } catch (err) {
      setError(message(err, "Could not save."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate data-testid="step-location">
      <StepHeading title="Where to find you" hint="Drag the pin to your entrance, or click the map. Patients get directions to this spot." />
      <div className="space-y-4">
        <LocationMap value={point} onChange={place} />
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className={softButtonClass} onClick={locate}>
            <Icon name="my_location" className="text-[16px]" />
            Use my location
          </button>
          {note && (
            <span data-testid="location-note" className="text-[11px] text-slate-500">
              {note}
            </span>
          )}
        </div>
        <Field id="location-address" label="Address" hint="Street, area or a landmark: e.g. Bole Road, near Edna Mall">
          <input id="location-address" className={fieldClass} maxLength={200} value={address} onChange={(e) => setAddress(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field id="location-lat" label="Latitude">
            <input id="location-lat" className={fieldClass} inputMode="decimal" value={latitude} onChange={(e) => setLatitude(e.target.value)} />
          </Field>
          <Field id="location-lng" label="Longitude">
            <input id="location-lng" className={fieldClass} inputMode="decimal" value={longitude} onChange={(e) => setLongitude(e.target.value)} />
          </Field>
        </div>
      </div>
      <StepError message={error} />
      <StepNav onBack={onBack} busy={busy} />
    </form>
  );
}

// --- 4. documents ------------------------------------------------------------------------------

const ACCEPT = "application/pdf,image/jpeg,image/png,image/webp,.pdf,.jpg,.jpeg,.png,.webp";
const MAX_BYTES = 10 * 1024 * 1024;

function DocumentRow({ item, onUploaded }: { item: ApplicationDocument; onUploaded: (application: Application) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function choose(file: File | undefined) {
    if (!file) return;
    setError(null);
    if (file.size > MAX_BYTES) return setError("This file is larger than 10 MB.");
    if (!/\.(pdf|jpe?g|png|webp)$/i.test(file.name)) return setError("Choose a PDF, JPEG, PNG or WebP file.");
    setBusy(true);
    try {
      onUploaded(await apiUpload<Application>(`onboarding/documents/${item.kind}`, file));
    } catch (err) {
      setError(message(err, "The upload failed."));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <li data-testid="document-row" data-kind={item.kind} data-uploaded={item.uploaded ? "true" : "false"} className="rounded-2xl border border-[#E2E8F0] bg-[#F8FAFB] p-4">
      <div className="flex items-start gap-3">
        <span
          className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${item.uploaded ? "bg-[#1E5852] text-white" : "bg-white text-slate-400"}`}
        >
          <Icon name={item.uploaded ? "check" : "upload_file"} className="text-[18px]" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-[#12302C]">{item.label}</p>
          <p data-testid="document-status" className="mt-0.5 truncate text-[11px] text-slate-500">
            {busy
              ? "Uploading…"
              : item.uploaded
                ? `Uploaded: ${item.filename} (${formatSize(item.size ?? 0)})`
                : "Required: PDF, JPEG, PNG or WebP, up to 10 MB"}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5 sm:flex-row sm:items-center">
          {item.uploaded && (
            <a href={fileUrl(`onboarding/documents/${item.kind}`)} target="_blank" rel="noopener" className="text-[11px] font-semibold text-[#1E5852] hover:underline">
              View
            </a>
          )}
          <button type="button" className={softButtonClass} disabled={busy} onClick={() => input.current?.click()}>
            {item.uploaded ? "Replace" : "Upload"}
          </button>
        </div>
      </div>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="hidden"
        aria-label={`${item.label} file`}
        onChange={(e) => void choose(e.target.files?.[0])}
      />
      {error && (
        <p role="alert" className="mt-2 text-[11px] text-red-600">
          {error}
        </p>
      )}
    </li>
  );
}

export function DocumentsStep({ application, onSaved, onBack, onChanged }: StepProps & { onChanged: (a: Application) => void }) {
  const [license, setLicense] = useState(application.documents.license_number ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const missing = application.documents.items.filter((d) => !d.uploaded);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!license.trim()) return setError("Enter the facility license number.");
    if (missing.length) return setError(`Upload every document first: ${missing.map((d) => d.label).join(", ")}.`);
    setBusy(true);
    setError(null);
    try {
      onSaved(await apiFetch<Application>("onboarding/documents", { method: "PATCH", body: { license_number: license.trim() } }));
    } catch (err) {
      setError(message(err, "Could not save."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate data-testid="step-documents">
      <StepHeading title="Documents" hint="All four are required. Endod checks them before the demo; only you and Endod can see them." />
      <div className="space-y-4">
        <Field id="documents-license" label="Ministry of Health facility license number">
          <input id="documents-license" className={fieldClass} maxLength={60} value={license} onChange={(e) => setLicense(e.target.value)} />
        </Field>
        <ul className="space-y-2.5">
          {application.documents.items.map((item) => (
            <DocumentRow key={item.kind} item={item} onUploaded={onChanged} />
          ))}
        </ul>
      </div>
      <StepError message={error} />
      <StepNav onBack={onBack} busy={busy} />
    </form>
  );
}

// --- 5. the demo -------------------------------------------------------------------------------

export function DemoStep({ application, onChanged, onBack, onNext }: {
  application: Application;
  onChanged: (application: Application) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  return (
    <form
      data-testid="step-demo"
      onSubmit={(event) => {
        event.preventDefault();
        onNext();
      }}
    >
      <StepHeading
        title="Book a demo"
        hint="A 30-minute video call with Endod: we show you the portal and check your details. We text the time to your mobile."
      />
      <DemoPicker current={application.demo?.demo_at ?? null} onBooked={onChanged} />
      <StepNav onBack={onBack} disabled={!application.demo} />
    </form>
  );
}

// --- 6. review ---------------------------------------------------------------------------------

function Section({ title, onEdit, children }: { title: string; onEdit: () => void; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-[#E2E8F0] bg-[#F8FAFB] p-4">
      <div className="mb-1.5 flex items-center justify-between">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">{title}</h3>
        <button type="button" onClick={onEdit} className="text-[11px] font-semibold text-[#1E5852] hover:underline">
          Edit
        </button>
      </div>
      <div className="space-y-0.5 text-sm text-[#12302C]">{children}</div>
    </section>
  );
}

export function ReviewStep({ application, onBack, onEdit, onSubmitted }: {
  application: Application;
  onBack: () => void;
  onEdit: (step: number) => void;
  onSubmitted: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { contact, facility, location, documents, demo } = application;
  const services = facility.services.map((key) => SERVICES.find((s) => s.key === key)?.label ?? key).join(", ");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiFetch<Application>("onboarding/submit", { method: "POST" });
      onSubmitted();
    } catch (err) {
      setError(message(err, "The application could not be sent."));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate data-testid="step-review">
      <StepHeading title="Review and submit" hint="Check everything once more. After you submit, Endod reviews your application and meets you at the demo." />
      <div className="space-y-2.5" data-testid="review-summary">
        <Section title="Contact person" onEdit={() => onEdit(0)}>
          <p className="font-semibold">{contact.full_name}</p>
          <p className="text-xs text-slate-500">
            {contact.title} · {contact.phone} · {contact.email}
          </p>
        </Section>
        <Section title="Facility" onEdit={() => onEdit(1)}>
          <p className="font-semibold">
            {facility.name}
            {facility.name_am && <span className="font-normal text-slate-500"> · {facility.name_am}</span>}
          </p>
          <p className="text-xs text-slate-500">
            {facility.ownership === "public" ? "Public" : "Private"} {facility.facility_type} in {facility.city} · {facility.phone}
          </p>
          <p className="text-xs text-slate-500">{services}</p>
          <p className="text-xs text-slate-500">{facility.open_hours}</p>
        </Section>
        <Section title="Location" onEdit={() => onEdit(2)}>
          <p>{location.address}</p>
          <p className="text-xs text-slate-500">
            {location.latitude?.toFixed(6)}, {location.longitude?.toFixed(6)}
          </p>
        </Section>
        <Section title="Documents" onEdit={() => onEdit(3)}>
          <p className="text-xs text-slate-500">License number {documents.license_number}</p>
          {documents.items.map((item) => (
            <p key={item.kind} className="text-xs">
              <Icon name={item.uploaded ? "check_circle" : "error"} className={`mr-1 align-middle text-[14px] ${item.uploaded ? "text-[#1E5852]" : "text-red-500"}`} />
              {item.label}
            </p>
          ))}
        </Section>
        <Section title="Demo" onEdit={() => onEdit(4)}>
          <p>{demo ? `${formatDemo(demo.demo_at)} (Addis Ababa time)` : "Not booked"}</p>
        </Section>
      </div>
      <StepError message={error} />
      <StepNav onBack={onBack} busy={busy} nextLabel={application.status === "rejected" ? "Resubmit application" : "Submit application"} disabled={!application.complete} />
    </form>
  );
}
