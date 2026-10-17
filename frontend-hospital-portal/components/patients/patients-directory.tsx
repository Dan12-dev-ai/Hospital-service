"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { PatientsHeader } from "@/components/patients/patients-header";
import { PatientsKpis } from "@/components/patients/patients-kpis";
import { PatientsToolbar } from "@/components/patients/patients-toolbar";
import { PatientsTable } from "@/components/patients/patients-table";
import { RegisterPatientModal } from "@/components/patients/register-patient-modal";
import {
  patientDepartments,
  patientWards,
  patients as allPatients,
} from "@/lib/patients-data";
import type { PatientTabKey } from "@/lib/patient-types";

export function PatientsDirectory() {
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<PatientTabKey>("all");
  const [department, setDepartment] = useState(patientDepartments[0]);
  const [ward, setWard] = useState(patientWards[0]);
  const [denseView, setDenseView] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

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
    return allPatients.filter((patient) => {
      const haystack = [
        patient.name,
        patient.nameAm,
        patient.id,
        patient.sph,
        patient.demographics,
        patient.doctor,
        patient.doctorDepartment,
        patient.diagnosis,
      ]
        .join(" ")
        .toLowerCase();

      const matchesSearch = !search || haystack.includes(search);
      const matchesTab = tab === "all" || patient.status === tab;
      const matchesDepartment =
        department === patientDepartments[0] ||
        patient.department === department;
      const matchesWard = ward === patientWards[0] || patient.ward === ward;

      return matchesSearch && matchesTab && matchesDepartment && matchesWard;
    });
  }, [query, tab, department, ward]);

  return (
    <div className="flex w-full flex-col gap-5">
      <PatientsHeader onRegister={() => setModalOpen(true)} />
      <PatientsKpis />
      <div className="flex w-full flex-col gap-4">
        <PatientsToolbar
          ref={searchRef}
          query={query}
          onQueryChange={setQuery}
          tab={tab}
          onTabChange={setTab}
          department={department}
          onDepartmentChange={setDepartment}
          ward={ward}
          onWardChange={setWard}
          denseView={denseView}
          onDenseViewToggle={() => setDenseView((value) => !value)}
          departments={patientDepartments}
          wards={patientWards}
        />
        <PatientsTable patients={filtered} dense={denseView} />
      </div>

      <RegisterPatientModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
      />
    </div>
  );
}
