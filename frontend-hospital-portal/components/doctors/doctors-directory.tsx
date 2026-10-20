"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { DoctorsHeader } from "@/components/doctors/doctors-header";
import { DoctorsKpis } from "@/components/doctors/doctors-kpis";
import { DoctorsToolbar } from "@/components/doctors/doctors-toolbar";
import { DoctorsTable } from "@/components/doctors/doctors-table";
import { AddDoctorModal, DutyModal, ProfileModal } from "@/components/doctors/doctor-modals";
import { ErrorState, LoadingState, RoleGate } from "@/components/common/states";
import { useSignedIn } from "@/components/session/session-context";
import { useApi } from "@/lib/api";
import type { Department, DoctorList, Hospital, Staff } from "@/lib/api-types";
import { toDoctorView, type Doctor, type DoctorStatusFilter } from "@/lib/doctor-types";

export function DoctorsDirectory() {
  return (
    <RoleGate roles="any" what="the doctors directory">
      <DoctorsLoaded />
    </RoleGate>
  );
}

function DoctorsLoaded() {
  const signedIn = useSignedIn();
  if (!signedIn) return null;
  return <Doctors staff={signedIn.staff} hospital={signedIn.hospital} />;
}

type Dialog = { kind: "add" } | { kind: "duty"; doctor: Doctor } | { kind: "profile"; doctor: Doctor } | null;

function Doctors({ staff, hospital }: { staff: Staff; hospital: Hospital }) {
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.trim());
  const [department, setDepartment] = useState("all");
  const [rank, setRank] = useState("all");
  const [status, setStatus] = useState<DoctorStatusFilter>("all");
  const [dialog, setDialog] = useState<Dialog>(null);

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
    const search = new URLSearchParams();
    if (deferredQuery) search.set("q", deferredQuery);
    if (department !== "all") search.set("department_id", department);
    if (rank !== "all") search.set("rank", rank);
    if (status !== "all") search.set("status", status);
    const text = search.toString();
    return text ? `doctors?${text}` : "doctors";
  }, [deferredQuery, department, rank, status]);

  const list = useApi<DoctorList>(path);
  const departments = useApi<Department[]>("departments");
  const doctors = useMemo(() => (list.data?.items ?? []).map(toDoctorView), [list.data]);
  const counts = list.data?.counts;
  const filtered = Boolean(deferredQuery) || department !== "all" || rank !== "all" || status !== "all";

  return (
    <div className="flex w-full flex-col">
      <DoctorsHeader
        activeCount={counts ? counts.all - counts["off-duty"] : null}
        hospitalName={hospital.name}
        canAdd={staff.role === "admin"}
        onAdd={() => setDialog({ kind: "add" })}
      />
      <DoctorsKpis counts={counts ?? null} />
      <DoctorsToolbar
        ref={searchRef}
        query={query}
        onQueryChange={setQuery}
        department={department}
        onDepartmentChange={setDepartment}
        departments={departments.data ?? []}
        rank={rank}
        onRankChange={setRank}
        status={status}
        onStatusChange={setStatus}
        counts={counts ?? null}
      />
      {list.error ? (
        <ErrorState message={list.error.message} onRetry={list.reload} />
      ) : !list.data ? (
        <LoadingState label="Loading doctors…" />
      ) : (
        <DoctorsTable
          doctors={doctors}
          filtered={filtered}
          canAdd={staff.role === "admin"}
          canSetDuty={(doctor) => doctor.id === staff.id || staff.role === "admin" || staff.role === "nurse"}
          canEditProfile={staff.role === "admin"}
          onSetDuty={(doctor) => setDialog({ kind: "duty", doctor })}
          onEditProfile={(doctor) => setDialog({ kind: "profile", doctor })}
        />
      )}

      {dialog?.kind === "add" && (
        <AddDoctorModal
          departments={departments.data ?? []}
          onClose={() => setDialog(null)}
          onCreated={list.reload}
        />
      )}
      {dialog?.kind === "duty" && (
        <DutyModal
          doctor={dialog.doctor}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null);
            list.reload();
          }}
        />
      )}
      {dialog?.kind === "profile" && (
        <ProfileModal
          doctor={dialog.doctor}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null);
            list.reload();
          }}
        />
      )}
    </div>
  );
}
