"use client";

import Image from "next/image";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import type { Doctor } from "@/lib/doctor-types";

export function DoctorRow({ doctor }: { doctor: Doctor }) {
  const { showToast } = useDashboard();

  return (
    <tr className="transition-colors hover:bg-surface-container-low/60">
      {/* Doctor Profile & License */}
      <td className="px-5 py-3.5">
        <div className="flex items-center gap-3">
          <div className="h-11 w-11 shrink-0 overflow-hidden rounded-full bg-surface-container-high shadow-sm">
            <Image
              src={doctor.photo}
              alt={`Portrait of ${doctor.name}`}
              width={44}
              height={44}
              className="h-full w-full object-cover"
            />
          </div>
          <div className="flex min-w-0 flex-col">
            <div className="flex items-center gap-1.5">
              <span className="truncate text-label-lg font-label-lg font-semibold text-on-surface">
                {doctor.name}
              </span>
              <span className="truncate text-label-sm font-label-sm text-outline">
                ({doctor.nameAm})
              </span>
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-label-sm font-label-sm text-outline">
              <span>{doctor.license}</span>
              <span>•</span>
              <span>{doctor.credentials}</span>
              <span>•</span>
              <span>{doctor.demographics}</span>
            </div>
          </div>
        </div>
      </td>

      {/* Department & Specialty */}
      <td className="px-4 py-3.5">
        <div className="flex flex-col">
          <span className="font-medium text-on-surface">
            {doctor.departmentLabel}
          </span>
          <span className="text-label-sm font-label-sm text-outline">
            {doctor.specialty} • {doctor.rankLabel}
          </span>
        </div>
      </td>

      {/* Duty Status */}
      <td className="px-4 py-3.5">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-label-sm font-label-sm ${doctor.statusBadgeClass}`}
        >
          <span
            className={`h-2 w-2 rounded-full ${doctor.statusDotClass}`}
          />
          <span>{doctor.statusLabel}</span>
        </span>
      </td>

      {/* Today's Patient Load */}
      <td className="px-4 py-3.5">
        <div className="flex w-36 flex-col gap-1">
          <div className="flex items-center justify-between text-label-sm font-label-sm">
            <span className="font-medium text-on-surface">
              {doctor.loadLabel}
            </span>
            <span className="text-outline">{doctor.loadCaption}</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-surface-container">
            <div
              className={`h-1.5 rounded-full ${doctor.loadBarClass}`}
              style={{ width: `${doctor.loadPercent}%` }}
            />
          </div>
        </div>
      </td>

      {/* Contact & Extension */}
      <td className="px-4 py-3.5">
        <div className="flex flex-col text-label-sm font-label-sm">
          <span className="font-medium text-on-surface">{doctor.phone}</span>
          <span className="text-outline">{doctor.extension}</span>
        </div>
      </td>

      {/* Actions */}
      <td className="px-5 py-3.5 text-right">
        <div className="flex items-center justify-end gap-1">
          <ActionButton
            icon="badge"
            title="View Profile"
            onClick={() => showToast(doctor.profileMessage)}
            hoverClass="hover:text-primary"
          />
          <ActionButton
            icon="calendar_month"
            title="Schedule"
            onClick={() => showToast(doctor.scheduleMessage)}
            hoverClass="hover:text-primary"
          />
          <ActionButton
            icon="chat"
            title="Message"
            onClick={() => showToast(doctor.messageMessage)}
            hoverClass="hover:text-primary"
          />
          <ActionButton
            icon="more_vert"
            title="More"
            hoverClass="hover:text-on-surface"
          />
        </div>
      </td>
    </tr>
  );
}

function ActionButton({
  icon,
  title,
  onClick,
  hoverClass,
}: {
  icon: string;
  title: string;
  onClick?: () => void;
  hoverClass: string;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className={`rounded-lg p-1.5 text-outline transition-all hover:bg-surface-container ${hoverClass}`}
    >
      <Icon name={icon} className="text-[19px]" />
    </button>
  );
}
