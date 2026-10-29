"use client";

import { Icon } from "@/components/ui/icon";

export function DoctorsHeader({
  activeCount,
  hospitalName,
  canAdd,
  onAdd,
}: {
  activeCount: number | null;
  hospitalName: string;
  canAdd: boolean;
  onAdd: () => void;
}) {
  return (
    <header className="flex flex-col justify-between gap-4 border-b border-surface-container pb-6 md:flex-row md:items-center">
      <div>
        <h1 className="flex items-center gap-2 text-headline-lg font-headline-lg text-on-surface">
          Physicians &amp; Specialists
          {activeCount !== null && (
            <span className="rounded-full bg-surface-container-high px-2 py-0.5 text-label-md font-label-md font-medium text-on-surface-variant">
              {activeCount} Active
            </span>
          )}
        </h1>
        <p className="mt-0.5 text-body-sm font-body-sm text-on-surface-variant">{hospitalName}</p>
      </div>

      {canAdd && (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onAdd}
            className="flex items-center gap-2 rounded-full bg-black px-5 py-2.5 text-label-md font-label-md text-white shadow-sm transition-all hover:bg-neutral-800"
          >
            <Icon name="person_add" className="text-[20px]" />
            <span>
              + Add Doctor <span className="font-normal opacity-90">(አዲስ ሐኪም መዝግብ)</span>
            </span>
          </button>
        </div>
      )}
    </header>
  );
}
