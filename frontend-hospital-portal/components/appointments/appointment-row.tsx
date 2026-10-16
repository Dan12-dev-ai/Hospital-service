"use client";

import Image from "next/image";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import type { AppointmentRow } from "@/lib/appointment-types";

export function AppointmentRow({ row }: { row: AppointmentRow }) {
  const { showToast } = useDashboard();

  return (
    <tr className="transition-colors hover:bg-surface-container-low/70">
      {/* Patient Profile & ID */}
      <td className="px-space-lg py-4">
        <div className="flex items-center gap-space-sm">
          {row.photo ? (
            <Image
              src={row.photo}
              alt={`Portrait of ${row.patientName}`}
              width={40}
              height={40}
              className="w-10 h-10 rounded-full object-cover shrink-0 shadow-xs"
            />
          ) : (
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-full shrink-0 shadow-xs shrink-0 font-label-md text-label-md font-bold ${row.initialsClass}`}
            >
              {row.initials}
            </div>
          )}
          <div className="flex min-w-0 flex-col">
            <div className="flex items-center gap-1.5">
              <span className="truncate font-label-md text-label-md font-semibold text-on-surface">
                {row.patientName}
              </span>
              <span className="truncate font-label-sm text-label-sm text-outline">
                ({row.patientNameAm})
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-outline font-label-sm text-label-sm">
              <span>{row.mrn}</span>
              <span>•</span>
              <span>{row.sph}</span>
              <span>•</span>
              <span className="bg-surface-container px-1 rounded text-on-surface-variant">
                {row.demographics}
              </span>
            </div>
          </div>
        </div>
      </td>

      {/* Scheduled Time & Type */}
      <td className="px-space-md py-4">
        <div className="flex flex-col">
          <span className="flex items-center gap-1 font-label-md text-label-md font-semibold text-on-surface">
            <Icon
              name="schedule"
              className={`text-[15px] ${
                row.timeAccent ? "text-primary" : "text-outline"
              }`}
            />
            {row.time}
          </span>
          <span className="font-body-sm text-body-sm text-outline">
            {row.visitType}
          </span>
        </div>
      </td>

      {/* Attending Doctor */}
      <td className="px-space-md py-4">
        <div className="flex flex-col">
          <span className="font-label-md text-label-md text-on-surface font-medium">
            {row.doctor}
          </span>
          <span className="font-body-sm text-body-sm text-outline">
            {row.doctorMeta}
          </span>
        </div>
      </td>

      {/* Visit Status */}
      <td className="px-space-md py-4">
        <span
          className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full font-label-sm text-label-sm ${row.statusClass}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${row.statusDotClass}`} />
          {row.statusLabel}
        </span>
      </td>

      {/* Priority / Notes */}
      <td className="px-space-md py-4">
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-md font-label-sm text-label-sm ${row.noteClass}`}
        >
          {row.note}
        </span>
      </td>

      {/* Actions */}
      <td className="px-space-lg py-4 text-right">
        <div className="inline-flex items-center gap-1">
          <button
            type="button"
            onClick={() => showToast(row.actionLabel)}
            className={`px-3 py-1.5 rounded-lg font-label-sm text-label-sm font-medium transition-colors ${
              row.actionPrimary
                ? "bg-primary-container text-on-primary hover:bg-primary shadow-xs"
                : "bg-surface-container text-on-surface hover:bg-primary-container hover:text-on-primary"
            }`}
          >
            {row.actionLabel}
          </button>
          <button
            type="button"
            className="w-8 h-8 rounded-lg flex items-center justify-center text-outline hover:text-on-surface hover:bg-surface-container transition-colors"
          >
            <Icon name="more_vert" className="text-[18px]" />
          </button>
        </div>
      </td>
    </tr>
  );
}
