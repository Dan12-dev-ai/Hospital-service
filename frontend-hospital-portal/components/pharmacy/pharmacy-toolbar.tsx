"use client";

import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import {
  pharmacyCategories,
  pharmacyDispensaries,
  pharmacyTabs,
} from "@/lib/pharmacy-data";
import type { PharmacyTabKey } from "@/lib/pharmacy-types";

type PharmacyToolbarProps = {
  tab: PharmacyTabKey;
  onTabChange: (tab: PharmacyTabKey) => void;
  dispensary: string;
  onDispensaryChange: (value: string) => void;
  category: string;
  onCategoryChange: (value: string) => void;
};

export function PharmacyToolbar({
  tab,
  onTabChange,
  dispensary,
  onDispensaryChange,
  category,
  onCategoryChange,
}: PharmacyToolbarProps) {
  return (
    <section className="flex flex-col justify-between gap-4 rounded-2xl bg-surface-container-lowest p-4 shadow-sm lg:flex-row lg:items-center">
      <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto">
        {pharmacyTabs.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => onTabChange(item.key)}
            className={cn(
              "rounded-full px-3.5 py-1.5 text-label-md font-label-md transition-all",
              item.key === "low-stock"
                ? tab === item.key
                  ? "bg-error-container text-on-error-container shadow-sm"
                  : "bg-error-container/30 text-on-error-container hover:bg-error-container/50"
                : tab === item.key
                  ? "bg-primary font-semibold text-on-primary shadow-sm"
                  : "bg-surface-container-low font-medium text-on-surface-variant hover:bg-surface-container"
            )}
          >
            {item.label} ({item.count})
          </button>
        ))}
      </div>

      <div className="flex w-full flex-wrap items-center justify-end gap-3 lg:w-auto">
        <SelectPill
          value={dispensary}
          onChange={onDispensaryChange}
          options={pharmacyDispensaries}
          ariaLabel="Filter by dispensary"
        />
        <SelectPill
          value={category}
          onChange={onCategoryChange}
          options={pharmacyCategories}
          ariaLabel="Filter by drug category"
        />
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
    <div className="relative">
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="cursor-pointer appearance-none rounded-xl bg-surface-container-low py-2 pl-3.5 pr-8 text-label-md font-label-md text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <Icon
        name="expand_more"
        className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[18px] text-outline"
      />
    </div>
  );
}
