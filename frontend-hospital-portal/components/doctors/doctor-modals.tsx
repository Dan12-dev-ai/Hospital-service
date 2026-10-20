"use client";

import { useState } from "react";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import {
  FormError,
  Modal,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { ApiError, apiFetch } from "@/lib/api";
import type { ApiDoctor, Department, DoctorRank, DutyStatus, Staff } from "@/lib/api-types";
import { DUTY_LABELS, RANK_OPTIONS, type Doctor } from "@/lib/doctor-types";

function messageOf(err: unknown, fallback: string) {
  return err instanceof ApiError ? err.message : fallback;
}

/** An admin creates a doctor's staff account; it comes with a one-time password. */
export function AddDoctorModal({
  departments,
  onClose,
  onCreated,
}: {
  departments: Department[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<{ email: string; password: string } | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<Staff & { temporary_password: string }>("staff", {
        method: "POST",
        body: {
          full_name: fullName.trim(),
          email: email.trim(),
          role: "doctor",
          phone: phone.trim() || null,
          department_id: departmentId || null,
        },
      });
      setCreated({ email: result.email, password: result.temporary_password });
      onCreated();
    } catch (err) {
      setError(messageOf(err, "Could not add the doctor."));
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <Modal title="Doctor added" icon="person_add" onClose={onClose} footer={<button type="button" onClick={onClose} className={primaryButtonClass}>Done</button>}>
        <p className="text-xs text-slate-600">
          Give this one-time password to the doctor in person. They choose their own password at first sign-in. It is
          not shown again.
        </p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-2xl bg-surface-container-low p-4 text-sm">
          <dt className="text-outline">Email</dt>
          <dd className="font-medium">{created.email}</dd>
          <dt className="text-outline">Password</dt>
          <dd data-testid="temporary-password" className="font-mono font-semibold">
            {created.password}
          </dd>
        </dl>
      </Modal>
    );
  }

  return (
    <Modal
      title="Add doctor"
      icon="person_add"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButtonClass}>
            Cancel
          </button>
          <button type="button" disabled={busy || !fullName.trim() || !email.trim()} onClick={submit} className={primaryButtonClass}>
            {busy ? "Adding…" : "Add doctor"}
          </button>
        </>
      }
    >
      <div>
        <label htmlFor="doctor-name" className={labelClass}>Full name</label>
        <input id="doctor-name" value={fullName} maxLength={120} onChange={(e) => setFullName(e.target.value)} className={inputClass} />
      </div>
      <div>
        <label htmlFor="doctor-email" className={labelClass}>Email</label>
        <input id="doctor-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="doctor-phone" className={labelClass}>Mobile (optional)</label>
          <input id="doctor-phone" type="tel" placeholder="0911 234 567" value={phone} onChange={(e) => setPhone(e.target.value)} className={inputClass} />
        </div>
        <div>
          <label htmlFor="doctor-department" className={labelClass}>Department (optional)</label>
          <select id="doctor-department" value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} className={inputClass}>
            <option value="">None</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
        </div>
      </div>
      <FormError message={error} />
    </Modal>
  );
}

/** A doctor sets their own duty status; admins and nurses set anyone's. */
export function DutyModal({ doctor, onClose, onSaved }: { doctor: Doctor; onClose: () => void; onSaved: () => void }) {
  const { showToast } = useDashboard();
  const [status, setStatus] = useState<DutyStatus>(doctor.source.duty_status);
  const [location, setLocation] = useState(doctor.source.duty_location ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch<ApiDoctor>(`doctors/${doctor.id}/duty`, {
        method: "PATCH",
        body: { duty_status: status, duty_location: status === "off-duty" ? null : location.trim() || null },
      });
      showToast(`${doctor.name}: ${DUTY_LABELS[status]}`);
      onSaved();
    } catch (err) {
      setError(messageOf(err, "Could not change the duty status."));
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Duty status — ${doctor.name}`}
      icon="schedule"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButtonClass}>Cancel</button>
          <button type="button" disabled={busy} onClick={submit} className={primaryButtonClass}>{busy ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div>
        <label htmlFor="duty-status" className={labelClass}>Status</label>
        <select id="duty-status" value={status} onChange={(e) => setStatus(e.target.value as DutyStatus)} className={inputClass}>
          {(Object.keys(DUTY_LABELS) as DutyStatus[]).map((key) => (
            <option key={key} value={key}>{DUTY_LABELS[key]}</option>
          ))}
        </select>
      </div>
      {status !== "off-duty" && (
        <div>
          <label htmlFor="duty-location" className={labelClass}>Where (optional)</label>
          <input id="duty-location" maxLength={60} placeholder="OPD Rm 204" value={location} onChange={(e) => setLocation(e.target.value)} className={inputClass} />
        </div>
      )}
      <FormError message={error} />
    </Modal>
  );
}

/** Directory details of a doctor (admins). */
export function ProfileModal({ doctor, onClose, onSaved }: { doctor: Doctor; onClose: () => void; onSaved: () => void }) {
  const { showToast } = useDashboard();
  const source = doctor.source;
  const [form, setForm] = useState({
    license_number: source.license_number ?? "",
    credentials: source.credentials ?? "",
    specialty: source.specialty ?? "",
    rank: source.rank ?? "",
    extension: source.extension ?? "",
    daily_capacity: source.load.capacity === null ? "" : String(source.load.capacity),
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function set(key: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submit() {
    const capacity = form.daily_capacity.trim();
    if (capacity && !/^\d{1,3}$/.test(capacity)) {
      setError("Daily capacity is a whole number of patients (1–500).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiFetch<ApiDoctor>(`doctors/${doctor.id}/profile`, {
        method: "PATCH",
        body: {
          license_number: form.license_number.trim() || null,
          credentials: form.credentials.trim() || null,
          specialty: form.specialty.trim() || null,
          rank: (form.rank || null) as DoctorRank | null,
          extension: form.extension.trim() || null,
          daily_capacity: capacity ? Number(capacity) : null,
        },
      });
      showToast(`Profile of ${doctor.name} saved`);
      onSaved();
    } catch (err) {
      setError(messageOf(err, "Could not save the profile."));
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Profile — ${doctor.name}`}
      icon="badge"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButtonClass}>Cancel</button>
          <button type="button" disabled={busy} onClick={submit} className={primaryButtonClass}>{busy ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="profile-license" className={labelClass}>Licence number</label>
          <input id="profile-license" maxLength={40} value={form.license_number} onChange={(e) => set("license_number", e.target.value)} className={inputClass} />
        </div>
        <div>
          <label htmlFor="profile-credentials" className={labelClass}>Credentials</label>
          <input id="profile-credentials" maxLength={80} placeholder="MD, FACP" value={form.credentials} onChange={(e) => set("credentials", e.target.value)} className={inputClass} />
        </div>
        <div>
          <label htmlFor="profile-specialty" className={labelClass}>Specialty</label>
          <input id="profile-specialty" maxLength={120} value={form.specialty} onChange={(e) => set("specialty", e.target.value)} className={inputClass} />
        </div>
        <div>
          <label htmlFor="profile-rank" className={labelClass}>Rank</label>
          <select id="profile-rank" value={form.rank} onChange={(e) => set("rank", e.target.value)} className={inputClass}>
            <option value="">Not set</option>
            {RANK_OPTIONS.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="profile-extension" className={labelClass}>Extension</label>
          <input id="profile-extension" maxLength={16} value={form.extension} onChange={(e) => set("extension", e.target.value)} className={inputClass} />
        </div>
        <div>
          <label htmlFor="profile-capacity" className={labelClass}>Patients per day</label>
          <input id="profile-capacity" inputMode="numeric" value={form.daily_capacity} onChange={(e) => set("daily_capacity", e.target.value)} className={inputClass} />
        </div>
      </div>
      <FormError message={error} />
    </Modal>
  );
}
