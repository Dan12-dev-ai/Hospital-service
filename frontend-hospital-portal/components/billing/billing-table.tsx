"use client";

import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { cardsIssuedToday } from "@/lib/billing-data";
import type { BillingRecord } from "@/lib/billing-types";

const COLUMNS = [
  { label: "Card # & Patient", align: "left" },
  { label: "Registration Channel", align: "left" },
  { label: "Card Type & Category", align: "left" },
  { label: "Fee & Payment", align: "left" },
  { label: "Status & Dispensation", align: "left" },
  { label: "Actions", align: "right" },
];

export function BillingTable({ records }: { records: BillingRecord[] }) {
  return (
    <section className="flex w-full flex-col overflow-hidden rounded-2xl bg-surface-container-lowest shadow-soft">
      <div className="custom-scrollbar overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="bg-surface-container-low text-label-sm font-label-sm uppercase tracking-wider text-outline">
              {COLUMNS.map((column) => (
                <th
                  key={column.label}
                  className={`py-3 px-4 font-semibold ${
                    column.align === "right" ? "text-right" : "text-left"
                  }`}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-variant">
            {records.length > 0 ? (
              records.map((record) => <BillingRow key={record.id} record={record} />)
            ) : (
              <tr>
                <td
                  colSpan={COLUMNS.length}
                  className="px-4 py-10 text-center text-body-sm font-body-sm text-on-surface-variant"
                >
                  No issued cards match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-col items-center justify-between gap-3 bg-surface-container-low px-4 py-3 text-body-sm font-body-sm text-outline sm:flex-row">
        <span>
          Showing 1-{records.length} of {cardsIssuedToday} issued cards |
          Rows: 15
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            disabled
            aria-label="Previous page"
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-container-lowest text-on-surface-variant shadow-soft transition-colors hover:bg-surface-container disabled:opacity-40"
          >
            <Icon name="chevron_left" className="text-[18px]" />
          </button>
          {[1, 2, 3].map((page) => (
            <PageButton key={page} page={page} active={page === 1} />
          ))}
          <span className="px-1">...</span>
          <PageButton page={33} />
          <button
            type="button"
            aria-label="Next page"
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-container-lowest text-on-surface-variant shadow-soft transition-colors hover:bg-surface-container"
          >
            <Icon name="chevron_right" className="text-[18px]" />
          </button>
        </div>
      </div>
    </section>
  );
}

function PageButton({ page, active }: { page: number; active?: boolean }) {
  return (
    <button
      type="button"
      className={`flex h-8 w-8 items-center justify-center rounded-lg text-label-md font-label-md transition-colors ${
        active
          ? "bg-black text-white"
          : "bg-surface-container-lowest text-on-surface-variant shadow-soft hover:bg-surface-container"
      }`}
    >
      {page}
    </button>
  );
}

function BillingRow({ record }: { record: BillingRecord }) {
  const { showToast } = useDashboard();

  return (
    <tr className="transition-colors hover:bg-surface-bright">
      {/* Card # & Patient */}
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-3">
          <div
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-label-md font-label-md ${record.avatarClass}`}
          >
            {record.initials}
          </div>
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-label-lg font-label-lg text-on-surface">
              {record.name}{" "}
              <span className="font-normal text-outline">({record.nameAm})</span>
            </span>
            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              <span className={`text-label-sm font-label-sm ${record.cardNumberClass}`}>
                {record.id}
              </span>
              <span className="text-outline">•</span>
              <span className="text-body-sm font-body-sm text-outline">
                MRN: {record.mrn}
              </span>
              <span className="text-outline">•</span>
              <span className="text-body-sm font-body-sm text-outline">
                {record.phone}
              </span>
            </div>
          </div>
        </div>
      </td>

      {/* Registration Channel */}
      <td className="whitespace-nowrap px-4 py-3.5">
        <div className="flex flex-col">
          <div className="flex items-center gap-1.5 text-label-md font-label-md text-on-surface">
            <Icon
              name={record.channelIcon}
              className={`text-[16px] ${record.channelIconClass}`}
            />
            <span>{record.channelLabel}</span>
          </div>
          <span className="text-body-sm font-body-sm text-outline">
            {record.channelMeta}
          </span>
        </div>
      </td>

      {/* Card Type & Category */}
      <td className="whitespace-nowrap px-4 py-3.5">
        <div className="flex flex-col">
          <span className="text-label-md font-label-md text-on-surface">
            {record.cardType}
          </span>
          <span className="text-body-sm font-body-sm text-outline">
            {record.cardTypeAm}
          </span>
        </div>
      </td>

      {/* Fee & Payment */}
      <td className="whitespace-nowrap px-4 py-3.5">
        <div className="flex flex-col">
          <span className="text-label-lg font-label-lg text-on-surface">
            {record.fee}
          </span>
          <span
            className={`mt-0.5 inline-flex w-max items-center gap-1 rounded-full px-2 py-0.5 text-label-sm font-label-sm ${record.paymentBadgeClass}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${record.paymentDotClass}`} />
            {record.paymentLabel}
          </span>
        </div>
      </td>

      {/* Status & Dispensation */}
      <td className="whitespace-nowrap px-4 py-3.5">
        <span
          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-label-sm font-label-sm ${record.statusBadgeClass}`}
        >
          <Icon name={record.statusIcon} className="text-[14px]" />
          {record.statusLabel}
        </span>
      </td>

      {/* Actions */}
      <td className="whitespace-nowrap px-4 py-3.5 text-right">
        <div className="inline-flex items-center gap-1">
          <button
            type="button"
            onClick={() => showToast(record.action.message)}
            className={`flex items-center gap-1 rounded-lg px-2.5 py-1 text-label-md font-label-md transition-colors ${
              record.action.variant === "primary"
                ? "bg-black text-white hover:bg-neutral-800"
                : "bg-surface-container-low text-black hover:bg-surface-container"
            }`}
          >
            <Icon name={record.action.icon} className="text-[16px]" />
            <span>{record.action.label}</span>
          </button>
          <button
            type="button"
            aria-label={`More options for ${record.id}`}
            onClick={() => showToast(`Opening card options for ${record.id}`)}
            className="rounded-lg p-1 text-outline transition-colors hover:text-on-surface"
          >
            <Icon name="more_vert" className="text-[18px]" />
          </button>
        </div>
      </td>
    </tr>
  );
}
