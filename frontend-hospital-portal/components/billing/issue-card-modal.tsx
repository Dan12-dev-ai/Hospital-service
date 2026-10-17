"use client";

import { useState } from "react";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";

const CARD_TYPES = [
  { value: "adult", label: "New Adult Outpatient (የአዋቂ አዲስ ካርድ) - ETB 50.00" },
  { value: "pediatric", label: "Pediatric Child Card (የህፃናት ካርድ) - ETB 50.00" },
  { value: "emergency", label: "Emergency Fast-Track Card (ድንገተኛ ካርድ) - ETB 100.00" },
  { value: "maternal", label: "Maternal & ANC Card (የእናቶች ካርድ) - Free" },
  { value: "chronic", label: "Chronic Care (የስኳር/ደም ግፊት ካርድ) - ETB 50.00" },
];

const PAYMENT_CHANNELS = [
  { value: "cash", label: "Cash Desk", icon: "payments" },
  { value: "telebirr", label: "Telebirr", icon: "phone_android" },
  { value: "cbe", label: "CBE Birr", icon: "account_balance" },
  { value: "cbhi", label: "CBHI Waiver", icon: "verified_user" },
];

export function IssueCardModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { showToast } = useDashboard();
  const [payment, setPayment] = useState("cash");

  if (!open) return null;

  function submit() {
    showToast("Patient card issued & sent to printer");
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/40 p-4 backdrop-blur-sm">
      <div className="flex w-full max-w-xl flex-col overflow-hidden rounded-3xl bg-surface-container-lowest shadow-xl">
        {/* Modal Header */}
        <div className="flex items-center justify-between bg-surface-container-low px-6 py-4">
          <div className="flex flex-col">
            <h2 className="text-headline-md font-headline-md text-on-surface">
              Issue New Patient Card
            </h2>
            <span className="text-body-sm font-body-sm text-outline">
              ቅዱስ ጳውሎስ ሆስፒታል • አዲስ ካርድ ምዝገባ
            </span>
          </div>
          <button
            type="button"
            aria-label="Close dialog"
            onClick={onClose}
            className="rounded-full p-1 text-outline transition-colors hover:bg-surface-variant hover:text-on-surface"
          >
            <Icon name="close" className="text-[20px]" />
          </button>
        </div>

        {/* Modal Body / Form */}
        <div className="flex flex-col gap-4 p-6">
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="issue-card-name"
              className="text-label-md font-label-md text-on-surface"
            >
              Full Name (English &amp; አማርኛ)
            </label>
            <input
              id="issue-card-name"
              type="text"
              placeholder="e.g. Abebe Bikila (አበበ ቢቂላ)"
              className="w-full rounded-xl bg-surface-container-low px-3 py-2 text-body-md font-body-md text-on-surface placeholder:text-outline focus:outline-none focus:ring-2 focus:ring-primary-container"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="issue-card-phone"
                className="text-label-md font-label-md text-on-surface"
              >
                Phone (+251)
              </label>
              <input
                id="issue-card-phone"
                type="tel"
                placeholder="091 100 0000"
                className="w-full rounded-xl bg-surface-container-low px-3 py-2 text-body-md font-body-md text-on-surface placeholder:text-outline focus:outline-none focus:ring-2 focus:ring-primary-container"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="issue-card-age"
                className="text-label-md font-label-md text-on-surface"
              >
                Age &amp; Gender
              </label>
              <div className="grid grid-cols-2 gap-2">
                <input
                  id="issue-card-age"
                  type="number"
                  placeholder="Age"
                  className="w-full rounded-xl bg-surface-container-low px-3 py-2 text-body-md font-body-md text-on-surface placeholder:text-outline focus:outline-none focus:ring-2 focus:ring-primary-container"
                />
                <select
                  aria-label="Gender"
                  defaultValue="Male"
                  className="w-full rounded-xl bg-surface-container-low px-2 py-2 text-body-md font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-container"
                >
                  <option>Male</option>
                  <option>Female</option>
                </select>
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="issue-card-type"
              className="text-label-md font-label-md text-on-surface"
            >
              Card Type &amp; Department
            </label>
            <select
              id="issue-card-type"
              defaultValue="adult"
              className="w-full rounded-xl bg-surface-container-low px-3 py-2 text-body-md font-body-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-container"
            >
              {CARD_TYPES.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-label-md font-label-md text-on-surface">
              Payment / Exemption Channel
            </span>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {PAYMENT_CHANNELS.map((channel) => (
                <label
                  key={channel.value}
                  className="flex cursor-pointer flex-col items-center justify-center rounded-xl border border-transparent bg-surface-container-low p-2.5 text-on-surface transition-colors hover:bg-surface-container has-[:checked]:bg-secondary-fixed has-[:checked]:text-on-secondary-fixed-variant"
                >
                  <input
                    type="radio"
                    name="payment-channel"
                    value={channel.value}
                    checked={payment === channel.value}
                    onChange={() => setPayment(channel.value)}
                    className="sr-only"
                  />
                  <Icon name={channel.icon} className="text-[20px]" />
                  <span className="mt-1 text-label-sm font-label-sm">
                    {channel.label}
                  </span>
                </label>
              ))}
            </div>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="flex items-center justify-end gap-3 bg-surface-container-low px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl px-4 py-2 text-label-lg font-label-lg text-on-surface-variant transition-colors hover:bg-surface-variant"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            className="flex items-center gap-2 rounded-xl bg-primary-container px-5 py-2 text-label-lg font-label-lg text-on-primary shadow-soft transition-all hover:bg-primary"
          >
            <Icon name="print" className="text-[18px]" />
            <span>Issue &amp; Print Card</span>
          </button>
        </div>
      </div>
    </div>
  );
}
