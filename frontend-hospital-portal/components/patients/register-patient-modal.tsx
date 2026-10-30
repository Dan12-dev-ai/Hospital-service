"use client";

import { useState } from "react";
import {
  FormError,
  Modal,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { ApiError, apiFetch } from "@/lib/api";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { ApiPatient } from "@/lib/api-types";

type Payer = "cash" | "cbhi" | "private" | "credit";

const PAYERS: { value: Payer; label: string }[] = [
  { value: "cash", label: "Cash" },
  { value: "cbhi", label: "CBHI (community insurance)" },
  { value: "private", label: "Private insurance" },
  { value: "credit", label: "Credit agreement" },
];

/** Registers a patient (POST /patients); the hospital number is issued by the backend. */
export function RegisterPatientModal({
  onClose,
  onRegistered,
}: {
  onClose: () => void;
  onRegistered: (patient: ApiPatient) => void;
}) {
  const [form, setForm] = useState({
    full_name: "",
    full_name_am: "",
    sex: "female",
    birth: "dob" as "dob" | "age",
    date_of_birth: "",
    age_years: "",
    phone: "",
    payer: "cash" as Payer,
    payer_number: "",
    claimed_dedan_id: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState(false);
  const [busy, setBusy] = useState(false);

  function set(key: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
    setDuplicate(false);
  }

  async function submit(confirmDuplicate: boolean) {
    if (form.full_name.trim().length < 2) return setError("Enter the patient's full name.");
    if (form.birth === "age" && form.age_years && !/^\d{1,3}$/.test(form.age_years)) {
      return setError("Age is a whole number of years.");
    }
    setBusy(true);
    setError(null);
    try {
      const patient = await apiFetch<ApiPatient>("patients", {
        method: "POST",
        body: {
          full_name: form.full_name.trim(),
          full_name_am: form.full_name_am.trim() || null,
          sex: form.sex,
          date_of_birth: form.birth === "dob" && form.date_of_birth ? form.date_of_birth : null,
          age_years: form.birth === "age" && form.age_years ? Number(form.age_years) : null,
          phone: form.phone.trim() || null,
          payer: form.payer,
          payer_number: form.payer_number.trim() || null,
          // Only a claim: Endod confirms the account when the patient is linked from their page.
          claimed_dedan_id: form.claimed_dedan_id.trim() || null,
          confirm_duplicate: confirmDuplicate,
        },
      });
      onRegistered(patient);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not register the patient.";
      setError(message);
      // Same name and phone already registered: the backend asks for confirmation.
      setDuplicate(err instanceof ApiError && err.status === 409 && message.includes("confirm_duplicate"));
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Register New Patient (አዲስ ታካሚ ምዝገባ)"
      icon="person_add"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButtonClass}>
            Cancel
          </button>
          {duplicate ? (
            <button type="button" disabled={busy} onClick={() => submit(true)} className={primaryButtonClass}>
              Register anyway
            </button>
          ) : (
            <button type="button" disabled={busy} onClick={() => submit(false)} className={primaryButtonClass}>
              {busy ? "Registering…" : "Complete Registration"}
            </button>
          )}
        </>
      }
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="patient-name" className={labelClass}>Full name</label>
            <input id="patient-name" maxLength={120} value={form.full_name} onChange={(e) => set("full_name", e.target.value)} className={inputClass} />
          </div>
          <div>
            <label htmlFor="patient-name-am" className={labelClass}>Name in Amharic</label>
            <input id="patient-name-am" maxLength={120} value={form.full_name_am} onChange={(e) => set("full_name_am", e.target.value)} className={inputClass} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="patient-sex" className={labelClass}>Sex</label>
            <Select value={form.sex} onValueChange={(v) => set("sex", v ?? form.sex)}>
              <SelectTrigger id="patient-sex" className="w-full cursor-pointer">
                <SelectValue>{(v) => (v === "female" ? "Female (ሴት)" : "Male (ወንድ)")}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="female">Female (ሴት)</SelectItem>
                <SelectItem value="male">Male (ወንድ)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <label htmlFor="patient-birth" className={labelClass}>Birth</label>
            <Select value={form.birth} onValueChange={(v) => set("birth", v ?? form.birth)}>
              <SelectTrigger id="patient-birth" className="w-full cursor-pointer">
                <SelectValue>{(v) => (v === "dob" ? "Date of birth known" : "Only the age is known")}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="dob">Date of birth known</SelectItem>
                <SelectItem value="age">Only the age is known</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        {form.birth === "dob" ? (
          <div>
            <label htmlFor="patient-dob" className={labelClass}>Date of birth</label>
            <input id="patient-dob" type="date" value={form.date_of_birth} onChange={(e) => set("date_of_birth", e.target.value)} className={inputClass} />
          </div>
        ) : (
          <div>
            <label htmlFor="patient-age" className={labelClass}>Age (years)</label>
            <input id="patient-age" inputMode="numeric" value={form.age_years} onChange={(e) => set("age_years", e.target.value)} className={inputClass} />
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="patient-phone" className={labelClass}>Mobile</label>
            <input id="patient-phone" type="tel" placeholder="0911 234 567" value={form.phone} onChange={(e) => set("phone", e.target.value)} className={inputClass} />
          </div>
          <div>
            <label htmlFor="patient-dedan" className={labelClass}>Endod ID given (optional, linked later)</label>
            <input id="patient-dedan" placeholder="DE482731" value={form.claimed_dedan_id} onChange={(e) => set("claimed_dedan_id", e.target.value)} className={inputClass} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="patient-payer" className={labelClass}>Payer</label>
            <Select value={form.payer} onValueChange={(v) => set("payer", v ?? form.payer)}>
              <SelectTrigger id="patient-payer" className="w-full cursor-pointer">
                <SelectValue>{(v) => (PAYERS.find((p) => p.value === v)?.label ?? v)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {PAYERS.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label htmlFor="patient-payer-number" className={labelClass}>Membership / policy no.</label>
            <input id="patient-payer-number" maxLength={40} value={form.payer_number} onChange={(e) => set("payer_number", e.target.value)} className={inputClass} />
          </div>
        </div>
      </div>
      <FormError message={error} />
    </Modal>
  );
}
