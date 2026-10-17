"use client";

import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";

export function RegisterPatientModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { showToast } = useDashboard();

  if (!open) return null;

  function submit() {
    showToast("Patient registered successfully & Digital Health ID generated!");
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/40 p-4 backdrop-blur-sm">
      <div className="flex w-full max-w-lg flex-col gap-4 rounded-3xl bg-surface-container-lowest p-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary text-on-primary">
              <Icon name="person_add" className="text-[18px]" />
            </div>
            <h3 className="text-headline-md font-headline-md text-on-surface">
              Register New Patient (አዲስ ታካሚ ምዝገባ)
            </h3>
          </div>
          <button
            type="button"
            aria-label="Close dialog"
            onClick={onClose}
            className="text-outline transition-colors hover:text-on-surface"
          >
            <Icon name="close" className="text-[20px]" />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label
              htmlFor="patient-name"
              className="mb-1 block text-label-sm font-label-sm text-on-surface-variant"
            >
              Full Name (English &amp; Amharic)
            </label>
            <input
              id="patient-name"
              type="text"
              placeholder="e.g., Abebech Mengistu (አበበች መንግስቱ)"
              className="w-full rounded-xl bg-surface-container-low px-3.5 py-2.5 font-body-md text-body-md text-on-surface placeholder:text-outline focus:outline-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="patient-dob"
                className="mb-1 block text-label-sm font-label-sm text-on-surface-variant"
              >
                Date of Birth / Age
              </label>
              <input
                id="patient-dob"
                type="text"
                placeholder="DD/MM/YYYY or Years"
                className="w-full rounded-xl bg-surface-container-low px-3.5 py-2.5 font-body-md text-body-md text-on-surface placeholder:text-outline focus:outline-none"
              />
            </div>
            <div>
              <label
                htmlFor="patient-sex"
                className="mb-1 block text-label-sm font-label-sm text-on-surface-variant"
              >
                Biological Sex
              </label>
              <select
                id="patient-sex"
                defaultValue="Female (ሴት)"
                className="w-full cursor-pointer rounded-xl bg-surface-container-low px-3.5 py-2.5 font-body-md text-body-md text-on-surface focus:outline-none"
              >
                <option>Female (ሴት)</option>
                <option>Male (ወንድ)</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="patient-phone"
                className="mb-1 block text-label-sm font-label-sm text-on-surface-variant"
              >
                Phone Number
              </label>
              <input
                id="patient-phone"
                type="tel"
                placeholder="+251 91..."
                className="w-full rounded-xl bg-surface-container-low px-3.5 py-2.5 font-body-md text-body-md text-on-surface placeholder:text-outline focus:outline-none"
              />
            </div>
            <div>
              <label
                htmlFor="patient-insurance"
                className="mb-1 block text-label-sm font-label-sm text-on-surface-variant"
              >
                Insurance / CBHI
              </label>
              <input
                id="patient-insurance"
                type="text"
                placeholder="CBHI / Private / Cash"
                className="w-full rounded-xl bg-surface-container-low px-3.5 py-2.5 font-body-md text-body-md text-on-surface placeholder:text-outline focus:outline-none"
              />
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl bg-surface-container px-4 py-2 text-label-md font-label-md text-on-surface-variant transition-colors hover:bg-surface-container-high"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            className="rounded-xl bg-primary px-5 py-2 text-label-md font-label-md text-on-primary shadow-glow transition-all hover:bg-surface-tint"
          >
            Complete Registration
          </button>
        </div>
      </div>
    </div>
  );
}
