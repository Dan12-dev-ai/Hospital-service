"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AppointmentsCommandBar } from "@/components/appointments/appointments-command-bar";
import { AppointmentsKpis } from "@/components/appointments/appointments-command-bar";
import { AppointmentsToolbar } from "@/components/appointments/appointments-toolbar";
import { AppointmentsTable } from "@/components/appointments/appointments-table";
import { appointmentRows } from "@/lib/appointments-list";
import { appointmentDepartments, appointmentVisitTypes } from "@/lib/appointments-list";
import { TOOLBAR_STATUSES } from "@/components/appointments/appointments-toolbar";
import type { AppointmentRow } from "@/lib/appointment-types";

const TOTAL_APPOINTMENTS = 145;

export function AppointmentsDirectory() {
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [department, setDepartment] = useState(appointmentDepartments[0]);
  const [visitType, setVisitType] = useState(appointmentVisitTypes[0]);
  const [status, setStatus] = useState("all");

  // ⌘K / Ctrl+K focuses the search input
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const filtered = useMemo(() => {
    const search = query.toLowerCase().trim();
    return appointmentRows.filter((row) => {
      const haystack = [
        row.patientName,
        row.patientNameAm,
        row.mrn,
        row.sph,
        row.doctor,
        row.doctorMeta,
        row.visitType,
      ]
        .join(" ")
        .toLowerCase();

      const matchesSearch = !search || haystack.includes(search);
      const matchesDepartment =
        department === "All Departments" || row.department === department;
      const matchesVisitType =
        visitType === "All Visit Types" || row.visitType === visitType;
      const matchesStatus = status === "all" || row.status === status;

      return (
        matchesSearch &&
        matchesDepartment &&
        matchesVisitType &&
        matchesStatus
      );
    });
  }, [query, department, visitType, status]);

  return (
    <div className="flex flex-col w-full">
      <AppointmentsCommandBar />
      <AppointmentsKpis />
      <AppointmentsToolbar
        ref={searchRef}
        query={query}
        onQueryChange={setQuery}
        department={department}
        onDepartmentChange={setDepartment}
        visitType={visitType}
        onVisitTypeChange={setVisitType}
        status={status}
        onStatusChange={setStatus}
      />
      <AppointmentsTable rows={filtered} total={TOTAL_APPOINTMENTS} />
    </div>
  );
}

export { appointmentDepartments, appointmentVisitTypes, TOOLBAR_STATUSES };
export type { AppointmentRow };

