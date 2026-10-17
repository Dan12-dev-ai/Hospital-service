"use client";

import { Icon } from "@/components/ui/icon";

export function ExpressBanner({ onOpen }: { onOpen: () => void }) {
  return (
    <section className="flex flex-col items-center justify-between gap-4 rounded-2xl bg-surface-container-low p-4 md:flex-row">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary-container text-on-primary">
          <Icon name="how_to_reg" className="text-[20px]" />
        </div>
        <div className="flex flex-col">
          <span className="text-label-lg font-label-lg text-on-surface">
            Express Triage Desk Card Issuance
          </span>
          <span className="text-body-sm font-body-sm text-outline">
            3-Step fast issuance: Patient Details → Channel Verification →
            Payment / CBHI Stamp
          </span>
        </div>
      </div>

      <div className="flex w-full items-center justify-end gap-2 md:w-auto">
        <div className="flex items-center -space-x-1.5">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary-container text-label-sm font-label-sm text-on-primary">
            1
          </span>
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-surface-variant text-label-sm font-label-sm text-on-surface-variant">
            2
          </span>
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-surface-variant text-label-sm font-label-sm text-on-surface-variant">
            3
          </span>
        </div>
        <button
          type="button"
          onClick={onOpen}
          className="rounded-lg bg-surface-container-lowest px-3 py-1.5 text-label-md font-label-md text-primary shadow-soft transition-colors hover:bg-surface-bright"
        >
          Open Registration Flow
        </button>
      </div>
    </section>
  );
}
