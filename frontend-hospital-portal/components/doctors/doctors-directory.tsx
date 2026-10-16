"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DoctorsHeader } from "@/components/doctors/doctors-header";
import { DoctorsKpis } from "@/components/doctors/doctors-kpis";
import { DoctorsToolbar } from "@/components/doctors/doctors-toolbar";
import { DoctorsTable } from "@/components/doctors/doctors-table";
import { doctors } from "@/lib/doctors-data";
import type { DoctorStatusFilter } from "@/lib/doctor-types";

const TOTAL_DOCTORS = 148;

export function DoctorsDirectory() {
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [department, setDepartment] = useState("all");
  const [rank, setRank] = useState("all");
  const [status, setStatus] = useState<DoctorStatusFilter>("all");

  // ⌘K / Ctrl+K focuses the search input (migrated from the template's
  // document-level keydown listener).
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
    return doctors.filter((doctor) => {
      const haystack = [
        doctor.name,
        doctor.nameAm,
        doctor.license,
        doctor.departmentLabel,
        doctor.specialty,
        doctor.rankLabel,
        doctor.phone,
        doctor.extension,
      ]
        .join(" ")
        .toLowerCase();

      const matchesSearch = !search || haystack.includes(search);
      const matchesDepartment =
        department === "all" || doctor.department === department;
      const matchesRank = rank === "all" || doctor.rank === rank;
      const matchesStatus = status === "all" || doctor.status === status;

      return matchesSearch && matchesDepartment && matchesRank && matchesStatus;
    });
  }, [query, department, rank, status]);

  return (
    <div className="flex w-full flex-col">
      <DoctorsHeader activeCount={42} />
      <DoctorsKpis />
      <DoctorsToolbar
        ref={searchRef}
        query={query}
        onQueryChange={setQuery}
        department={department}
        onDepartmentChange={setDepartment}
        rank={rank}
        onRankChange={setRank}
        status={status}
        onStatusChange={setStatus}
      />
      <DoctorsTable doctors={filtered} total={TOTAL_DOCTORS} />
    </div>
  );
}
