"use client";

import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { totalPrescriptionsToday } from "@/lib/pharmacy-data";
import type { PharmacyRecord } from "@/lib/pharmacy-types";

const COLUMNS = [
  { label: "RX ID & Patient", align: "left" },
  { label: "Prescribed Medication & Dosage", align: "left" },
  { label: "Prescribing Physician", align: "left" },
  { label: "Coverage / Payment", align: "left" },
  { label: "Status", align: "left" },
  { label: "Actions", align: "right" },
];

export function PharmacyTable({ records }: { records: PharmacyRecord[] }) {
  return (
    <section className="flex flex-col overflow-hidden rounded-3xl bg-surface-container-lowest shadow-sm">
      <div className="custom-scrollbar overflow-x-auto">
        <table className="w-full min-w-[1040px] border-collapse text-left">
          <thead>
            <tr className="bg-surface-container-low/70 font-label-sm text-label-sm uppercase tracking-wider text-outline">
              {COLUMNS.map((column) => (
                <th
                  key={column.label}
                  className={`px-5 py-3.5 font-semibold ${
                    column.align === "right" ? "text-right" : ""
                  }`}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-body-md text-body-md text-on-surface">
            {records.length > 0 ? (
              records.map((record) => (
                <PharmacyRow key={record.id} record={record} />
              ))
            ) : (
              <tr>
                <td
                  colSpan={COLUMNS.length}
                  className="px-5 py-10 text-center text-body-sm font-body-sm text-on-surface-variant"
                >
                  No prescriptions match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-col items-center justify-between gap-3 bg-surface-container-low/40 px-5 py-4 font-label-md text-label-md text-on-surface-variant sm:flex-row">
        <div className="flex items-center gap-4">
          <span>
            Showing <strong className="font-semibold text-on-surface">1-{records.length}</strong>{" "}
            of <strong className="font-semibold text-on-surface">{totalPrescriptionsToday}</strong>{" "}
            prescriptions
          </span>
          <span className="text-outline-variant">|</span>
          <div className="flex items-center gap-1.5">
            <span className="text-outline">Rows:</span>
            <select
              aria-label="Rows per page"
              defaultValue="15"
              className="cursor-pointer rounded-lg bg-surface-container-lowest px-2 py-1 text-on-surface focus:outline-none focus:ring-1 focus:ring-black/30"
            >
              <option>15</option>
              <option>25</option>
              <option>50</option>
            </select>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            disabled
            aria-label="Previous page"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-outline transition-colors hover:bg-surface-container hover:text-on-surface disabled:opacity-40"
          >
            <Icon name="chevron_left" className="text-[18px]" />
          </button>
          <PageButton page={1} active />
          <PageButton page={2} />
          <PageButton page={3} />
          <span className="w-6 text-center text-outline">...</span>
          <PageButton page={15} />
          <button
            type="button"
            aria-label="Next page"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-outline transition-colors hover:bg-surface-container hover:text-on-surface"
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
      className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${
        active
          ? "bg-black font-bold text-white shadow-sm"
          : "font-medium text-on-surface hover:bg-surface-container"
      }`}
    >
      {page}
    </button>
  );
}

function PharmacyRow({ record }: { record: PharmacyRecord }) {
  const { showToast } = useDashboard();

  return (
    <tr className="transition-colors hover:bg-surface-container-low/40">
      {/* RX ID & Patient */}
      <td className="px-5 py-4">
        <div className="flex items-center gap-3">
          <div
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl font-bold tracking-tight text-label-md ${record.avatarClass}`}
          >
            {record.initials}
          </div>
          <div className="flex min-w-0 flex-col">
            <span className="truncate font-label-lg text-label-lg font-bold text-on-surface">
              {record.name}
            </span>
            <span className="flex items-center gap-1.5 font-label-sm text-label-sm text-outline">
              <span className="font-medium text-on-surface-variant">
                {record.nameAm}
              </span>
              <span>•</span>
              <span className="font-mono font-medium text-black">
                {record.id}
              </span>
              <span>•</span>
              <span>MRN: {record.mrn}</span>
            </span>
          </div>
        </div>
      </td>

      {/* Prescribed Medication & Dosage */}
      <td className="px-5 py-4">
        <div className="flex flex-col">
          <span className="flex items-center gap-1.5 font-label-lg text-label-lg font-semibold text-on-surface">
            <Icon
              name={record.medicationIcon}
              className={`text-[16px] ${record.medicationIconClass}`}
            />
            {record.medication}
          </span>
          <span className="text-body-sm font-body-sm text-on-surface-variant">
            {record.dosage}
          </span>
        </div>
      </td>

      {/* Prescribing Physician */}
      <td className="px-5 py-4">
        <div className="flex flex-col">
          <span className="font-label-md text-label-md font-semibold text-on-surface">
            {record.physician}
          </span>
          <span className="text-body-sm font-body-sm text-outline">
            {record.physicianMeta}
          </span>
        </div>
      </td>

      {/* Coverage / Payment */}
      <td className="px-5 py-4">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-label-sm text-label-sm font-semibold ${record.coverageClass}`}
        >
          <Icon name={record.coverageIcon} className="text-[14px]" />
          {record.coverage}
        </span>
      </td>

      {/* Status */}
      <td className="px-5 py-4">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-label-sm text-label-sm font-bold ${record.statusClass}`}
        >
          {record.statusIcon ? (
            <Icon name={record.statusIcon} className="text-[14px]" />
          ) : (
            <span className={`h-1.5 w-1.5 rounded-full ${record.statusDotClass}`} />
          )}
          {record.statusLabel}
        </span>
      </td>

      {/* Actions */}
      <td className="px-5 py-4 text-right">
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => showToast(record.action.message)}
            className={`rounded-xl font-label-md text-label-md transition-all ${
              record.action.variant === "primary"
                ? "bg-black px-3.5 py-1.5 font-semibold text-white shadow-sm hover:bg-black"
                : "bg-surface-container-low px-3 py-1.5 font-medium text-on-surface hover:bg-surface-container"
            }`}
          >
            {record.action.label}
          </button>
          <button
            type="button"
            aria-label={`More options for ${record.id}`}
            onClick={() => showToast(`Opening Rx options for ${record.id}`)}
            className="rounded-lg p-1.5 text-outline transition-colors hover:bg-surface-container hover:text-on-surface"
          >
            <Icon name="more_vert" className="text-[18px]" />
          </button>
        </div>
      </td>
    </tr>
  );
}
