"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { Icon } from "@/components/ui/icon";
import { ApiError, apiFetch } from "@/lib/api";
import type { Hospital, HospitalKind, Staff } from "@/lib/api-types";
import {
  FormError,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";

/** The backend's password rule (app/security.py), checked here for quick feedback. */
export function passwordProblem(password: string): string | null {
  if (password.length < 10) return "Password must be at least 10 characters.";
  if (password.length > 200) return "Password must be at most 200 characters.";
  if (!/[a-z]/.test(password) || !/[A-Z]/.test(password)) {
    return "Password must include both upper and lower case letters.";
  }
  return null;
}

type Form = {
  hospital_name: string;
  hospital_name_am: string;
  kind: HospitalKind;
  city: string;
  phone: string;
  admin_name: string;
  admin_email: string;
  password: string;
  confirm: string;
};

const EMPTY: Form = {
  hospital_name: "",
  hospital_name_am: "",
  kind: "private",
  city: "",
  phone: "",
  admin_name: "",
  admin_email: "",
  password: "",
  confirm: "",
};

export function SignupForm() {
  const [form, setForm] = useState<Form>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ hospital: Hospital; staff: Staff } | null>(null);

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const problem = passwordProblem(form.password);
    if (problem) return setError(problem);
    if (form.password !== form.confirm) return setError("The two passwords do not match.");
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<{ hospital: Hospital; staff: Staff }>("onboarding", {
        method: "POST",
        redirectOn401: false,
        body: {
          hospital_name: form.hospital_name.trim(),
          hospital_name_am: form.hospital_name_am.trim() || null,
          kind: form.kind,
          city: form.city.trim(),
          phone: form.phone.trim() || null,
          admin_name: form.admin_name.trim(),
          admin_email: form.admin_email.trim(),
          password: form.password,
        },
      });
      setDone(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-up failed.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div data-testid="signup-pending" className="space-y-4">
        <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <Icon name="hourglass_top" className="mt-0.5 text-[22px] text-amber-600" />
          <div>
            <p className="font-bold">Pending approval by Endod</p>
            <p className="mt-1 text-xs">
              {done.hospital.name} is registered (hospital code <strong>{done.hospital.code}</strong>) and you are
              signed in as its administrator, {done.staff.full_name}. Endod checks every new hospital before patients
              can see it in the Endod app. Until then you can set up the portal: add your location, prices and
              services so the hospital can be listed as soon as it is approved.
            </p>
          </div>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Link href="/settings" className={`${primaryButtonClass} flex-1 py-2.5`}>
            Complete hospital profile
          </Link>
          <Link href="/" className={`${secondaryButtonClass} flex-1 py-2.5`}>
            Go to the dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <fieldset className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">Hospital</legend>
        <div className="sm:col-span-2">
          <label htmlFor="signup-hospital-name" className={labelClass}>
            Hospital name
          </label>
          <input
            id="signup-hospital-name"
            required
            maxLength={160}
            value={form.hospital_name}
            onChange={(event) => set("hospital_name", event.target.value)}
            className={inputClass}
          />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor="signup-hospital-name-am" className={labelClass}>
            Name in Amharic (optional)
          </label>
          <input
            id="signup-hospital-name-am"
            maxLength={160}
            value={form.hospital_name_am}
            onChange={(event) => set("hospital_name_am", event.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <label htmlFor="signup-kind" className={labelClass}>
            Kind
          </label>
          <select
            id="signup-kind"
            value={form.kind}
            onChange={(event) => set("kind", event.target.value as HospitalKind)}
            className={inputClass}
          >
            <option value="private">Private</option>
            <option value="public">Public</option>
          </select>
        </div>
        <div>
          <label htmlFor="signup-city" className={labelClass}>
            City
          </label>
          <input
            id="signup-city"
            required
            maxLength={100}
            value={form.city}
            onChange={(event) => set("city", event.target.value)}
            className={inputClass}
          />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor="signup-phone" className={labelClass}>
            Hospital phone (optional)
          </label>
          <input
            id="signup-phone"
            type="tel"
            placeholder="011 551 7611"
            value={form.phone}
            onChange={(event) => set("phone", event.target.value)}
            className={inputClass}
          />
        </div>
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">Administrator account</legend>
        <div>
          <label htmlFor="signup-admin-name" className={labelClass}>
            Your full name
          </label>
          <input
            id="signup-admin-name"
            required
            maxLength={120}
            value={form.admin_name}
            onChange={(event) => set("admin_name", event.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <label htmlFor="signup-admin-email" className={labelClass}>
            Work email
          </label>
          <input
            id="signup-admin-email"
            type="email"
            autoComplete="username"
            required
            value={form.admin_email}
            onChange={(event) => set("admin_email", event.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <label htmlFor="signup-password" className={labelClass}>
            Password
          </label>
          <input
            id="signup-password"
            type="password"
            autoComplete="new-password"
            required
            value={form.password}
            onChange={(event) => set("password", event.target.value)}
            className={inputClass}
          />
          <p className="mt-1 text-[11px] text-slate-400">At least 10 characters, with upper and lower case letters.</p>
        </div>
        <div>
          <label htmlFor="signup-confirm" className={labelClass}>
            Confirm password
          </label>
          <input
            id="signup-confirm"
            type="password"
            autoComplete="new-password"
            required
            value={form.confirm}
            onChange={(event) => set("confirm", event.target.value)}
            className={inputClass}
          />
        </div>
      </fieldset>

      <FormError message={error} />
      <button
        type="submit"
        disabled={busy || !form.hospital_name || !form.city || !form.admin_name || !form.admin_email || !form.password}
        className={`${primaryButtonClass} w-full py-2.5`}
      >
        {busy ? "Signing up…" : "Sign up"}
      </button>
      <p className="text-center text-xs text-slate-500">
        Already on Endod?{" "}
        <Link href="/login" className="font-semibold text-pine-green hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
