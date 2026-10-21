"use client";

import { RoleGate } from "@/components/common/states";
import { useSignedIn } from "@/components/session/session-context";
import { SharedList } from "@/components/patient/shared-list";
import { RECORD_READERS } from "@/lib/history-types";

/** Every record currently shared with this hospital through Endod. */
export function SharedRecordsPage() {
  return (
    <RoleGate roles={RECORD_READERS} what="records patients shared">
      <Loaded />
    </RoleGate>
  );
}

function Loaded() {
  const signedIn = useSignedIn();
  if (!signedIn) return null;
  return (
    <div className="flex w-full flex-col gap-5">
      <header>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-outline">Endod</p>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Shared with us</h1>
        <p className="mt-0.5 text-xs text-slate-500">
          Records patients shared with {signedIn.hospital.name} from their Endod app, read-only. A share ends when the
          patient stops it or at its end date.
        </p>
      </header>
      <SharedList path="shared" timeZone={signedIn.hospital.timezone} showPatient
        empty="When a patient shares records with this hospital from their Endod app, they appear here." />
    </div>
  );
}
