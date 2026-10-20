"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { PatientsHeader } from "@/components/patients/patients-header";
import { PatientsKpis } from "@/components/patients/patients-kpis";
import { PatientsToolbar } from "@/components/patients/patients-toolbar";
import { PatientsTable } from "@/components/patients/patients-table";
import { RegisterPatientModal } from "@/components/patients/register-patient-modal";
import { ErrorState, LoadingState, RoleGate } from "@/components/common/states";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { useSignedIn } from "@/components/session/session-context";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import type { ApiPatient, Department, Hospital, PatientList, PatientStats, PatientStatus, Staff } from "@/lib/api-types";
import { CLINICAL_EDITORS, PATIENT_REGISTRARS, STATUS_LABELS, toPatientView, type PatientTabKey } from "@/lib/patient-types";

const PAGE_SIZES = [15, 25, 50];

export function PatientsDirectory() {
  return (
    <RoleGate roles="any" what="the patient directory">
      <PatientsLoaded />
    </RoleGate>
  );
}

function PatientsLoaded() {
  const signedIn = useSignedIn();
  if (!signedIn) return null;
  return <Patients staff={signedIn.staff} hospital={signedIn.hospital} />;
}

function Patients({ staff, hospital }: { staff: Staff; hospital: Hospital }) {
  const { showToast } = useDashboard();
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.trim());
  const [tab, setTab] = useState<PatientTabKey>("all");
  const [department, setDepartment] = useState("all");
  const [ward, setWard] = useState("all");
  const [denseView, setDenseView] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);
  const [page, setPage] = useState(0);

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

  const path = useMemo(() => {
    const search = new URLSearchParams({ limit: String(pageSize), offset: String(page * pageSize) });
    if (deferredQuery) search.set("q", deferredQuery);
    if (tab !== "all") search.set("status", tab);
    if (department !== "all") search.set("department_id", department);
    if (ward !== "all") search.set("ward_id", ward);
    return `patients?${search.toString()}`;
  }, [deferredQuery, tab, department, ward, page, pageSize]);

  const list = useApi<PatientList>(path);
  const stats = useApi<PatientStats>("patients/stats");
  const departments = useApi<Department[]>("departments");
  const patients = useMemo(() => (list.data?.items ?? []).map(toPatientView), [list.data]);
  const clinicalDepartments = (departments.data ?? []).filter((d) => d.kind === "department" || d.kind === "clinic");
  const wards = (departments.data ?? []).filter((d) => d.kind === "ward");
  const filtered = Boolean(deferredQuery) || tab !== "all" || department !== "all" || ward !== "all";

  // Any filter change starts again from the first page.
  function resetPage<T>(setter: (value: T) => void) {
    return (value: T) => {
      setter(value);
      setPage(0);
    };
  }

  async function changeStatus(patientId: string, status: PatientStatus) {
    try {
      await apiFetch<ApiPatient>(`patients/${patientId}`, { method: "PATCH", body: { status } });
      showToast(`Status changed to ${STATUS_LABELS[status]}`);
      list.reload();
      stats.reload();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Could not change the status.");
    }
  }

  return (
    <div className="flex w-full flex-col gap-5">
      <PatientsHeader
        hospitalName={hospital.name}
        canRegister={PATIENT_REGISTRARS.includes(staff.role)}
        onRegister={() => setModalOpen(true)}
      />
      <PatientsKpis stats={stats.data} />
      <div className="flex w-full flex-col gap-4">
        <PatientsToolbar
          ref={searchRef}
          query={query}
          onQueryChange={resetPage(setQuery)}
          tab={tab}
          onTabChange={resetPage(setTab)}
          department={department}
          onDepartmentChange={resetPage(setDepartment)}
          ward={ward}
          onWardChange={resetPage(setWard)}
          denseView={denseView}
          onDenseViewToggle={() => setDenseView((value) => !value)}
          departments={clinicalDepartments}
          wards={wards}
          stats={stats.data}
        />
        {list.error ? (
          <ErrorState message={list.error.message} onRetry={list.reload} />
        ) : !list.data ? (
          <LoadingState label="Loading patients…" />
        ) : (
          <PatientsTable
            patients={patients}
            dense={denseView}
            total={list.data.total}
            offset={list.data.offset}
            pageSize={pageSize}
            pageSizes={PAGE_SIZES}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(0);
            }}
            onPrevious={() => setPage((value) => Math.max(0, value - 1))}
            onNext={() => setPage((value) => value + 1)}
            filtered={filtered}
            canRegister={PATIENT_REGISTRARS.includes(staff.role)}
            canChangeStatus={CLINICAL_EDITORS.includes(staff.role)}
            onChangeStatus={changeStatus}
          />
        )}
      </div>

      {modalOpen && (
        <RegisterPatientModal
          onClose={() => setModalOpen(false)}
          onRegistered={(patient) => {
            showToast(`${patient.full_name} registered as ${patient.mrn}`);
            setModalOpen(false);
            list.reload();
            stats.reload();
          }}
        />
      )}
    </div>
  );
}
