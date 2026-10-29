"use client";

import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import {
  billingClinics,
  billingPaymentMethods,
  billingTabs,
} from "@/lib/billing-data";
import type { BillingTabKey } from "@/lib/billing-types";

type BillingToolbarProps = {
  filterQuery: string;
  onFilterQueryChange: (value: string) => void;
  tab: BillingTabKey;
  onTabChange: (tab: BillingTabKey) => void;
  clinic: string;
  onClinicChange: (value: string) => void;
  paymentMethod: string;
  onPaymentMethodChange: (value: string) => void;
};

export function BillingToolbar({
  filterQuery,
  onFilterQueryChange,
  tab,
  onTabChange,
  clinic,
  onClinicChange,
  paymentMethod,
  onPaymentMethodChange,
}: BillingToolbarProps) {
  return (
    <section className="flex flex-col gap-3">
      <div className="custom-scrollbar flex items-center gap-2 overflow-x-auto pb-1">
        {billingTabs.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => onTabChange(item.key)}
            className={cn(
              "whitespace-nowrap rounded-full px-3.5 py-1.5 text-label-md font-label-md transition-all",
              tab === item.key
                ? "bg-black text-white shadow-soft"
                : "bg-surface-container-lowest text-on-surface-variant hover:bg-surface-container"
            )}
          >
            {item.label} ({item.count})
          </button>
        ))}
      </div>

      <div className="flex flex-col items-center justify-between gap-3 sm:flex-row">
        <div className="relative w-full sm:w-80">
          <Icon
            name="filter_list"
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[18px] text-outline"
          />
          <input
            type="text"
            value={filterQuery}
            onChange={(event) => onFilterQueryChange(event.target.value)}
            placeholder="Filter current results..."
            className="w-full rounded-xl bg-surface-container-lowest py-1.5 pl-9 pr-3 text-body-sm font-body-sm text-on-surface shadow-soft placeholder:text-outline focus:outline-none focus:ring-2 focus:ring-black"
          />
        </div>

        <div className="flex w-full items-center justify-end gap-2 overflow-x-auto sm:w-auto">
          <SelectPill
            value={clinic}
            onChange={onClinicChange}
            options={billingClinics}
            ariaLabel="Filter by clinic"
          />
          <SelectPill
            value={paymentMethod}
            onChange={onPaymentMethodChange}
            options={billingPaymentMethods}
            ariaLabel="Filter by payment method"
          />
        </div>
      </div>
    </section>
  );
}

function SelectPill({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  ariaLabel: string;
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v ?? value)}>
      <SelectTrigger aria-label={ariaLabel} className="cursor-pointer rounded-xl bg-surface-container-lowest py-1.5 pl-3 pr-8 text-label-md font-label-md text-on-surface-variant shadow-soft focus:outline-none focus:ring-2 focus:ring-black">
        <SelectValue>{(v) => options.find((o) => o.value === v)?.label ?? v}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
