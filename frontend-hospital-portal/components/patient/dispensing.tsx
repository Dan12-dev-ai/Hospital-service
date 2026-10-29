"use client";

import { Icon } from "@/components/ui/icon";
import { formatDateTime } from "@/lib/format";
import type { DispenseItem, Dispensing } from "@/lib/history-types";

const STATUS: Record<Dispensing["status"], { label: string; className: string }> = {
  not_dispensed: { label: "Not dispensed", className: "bg-slate-100 text-slate-700" },
  partly: { label: "Partly dispensed", className: "bg-amber-50 text-amber-800" },
  fully: { label: "Fully dispensed", className: "bg-neutral-50 text-neutral-800" },
};

const ITEM_STATUS: Record<DispenseItem["status"], string> = {
  not_given: "Not given",
  partly_given: "Partly given",
  given: "Given",
};

/** "14 of 21", "14 given", or the item's status when nothing was counted. */
function given(item: DispenseItem): string {
  if (item.given_total !== null && item.quantity_total !== null) return `${item.given_total} of ${item.quantity_total}`;
  if (item.given_total !== null) return `${item.given_total} given`;
  return ITEM_STATUS[item.status];
}

/**
 * What pharmacies gave from a prescription through Endod: an overall status
 * and each dispense (pharmacy as typed, time in the hospital's zone, per item).
 */
export function DispensingPanel({ dispensing, timeZone }: { dispensing: Dispensing; timeZone: string }) {
  const status = STATUS[dispensing.status];
  return (
    <section data-testid="dispensing" className="flex flex-col gap-2 rounded-xl bg-surface-container-low px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <Icon name="local_pharmacy" className="text-[16px] text-black" />
        <span className="text-xs font-bold text-slate-700">Dispensed</span>
        <span data-testid="dispensing-status" className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${status.className}`}>
          {status.label}
        </span>
      </div>
      {dispensing.dispenses.length === 0 ? (
        <p className="text-xs text-slate-500">No pharmacy has given medicine from this prescription through Endod yet.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {dispensing.dispenses.map((d) => (
            <li key={d.dispense_id} data-testid="dispense" className="text-xs text-slate-800">
              <span className="font-semibold">{d.pharmacy_name}</span>
              <span className="text-slate-500">, {formatDateTime(d.at, timeZone)}</span>
              <ul className="mt-0.5 flex flex-col gap-0.5 pl-4">
                {d.items.map((item) => (
                  <li key={item.item_index} data-testid="dispense-item">
                    {item.drug ?? `Item ${item.item_index + 1}`}: {given(item)}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
