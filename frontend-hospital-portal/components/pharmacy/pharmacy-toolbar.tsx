"use client";

import { cn } from "cn";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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
                  ? "bg-black font-semibold text-white shadow-sm"
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
    <Select value={value} onValueChange={(v) => onChange(v ?? value)}>
      <SelectTrigger aria-label={ariaLabel} className="cursor-pointer rounded-xl bg-surface-container-low py-2 pl-3.5 pr-8 text-label-md font-label-md text-on-surface focus:outline-none focus:ring-2 focus:ring-black/20">
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
