"use client";

import { useState, type FormEvent } from "react";
import { UserPlus } from "lucide-react";
import {
  ErrorState,
  FormError,
  Modal,
  RoleGate,
  dangerButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/common/states";
import { PageHeader } from "@/components/shell/dashboard-shell";
import { useToast } from "@/components/shell/toast";
import { useSignedIn } from "@/components/session/session-context";
import { CopyField } from "@/components/keys/confirm-code";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import { ROLE_LABELS, type DashboardRole, type Staff } from "@/lib/api-types";
import { timeAgo } from "@/lib/connect-types";
import { TeamListSkeleton } from "@/components/common/page-skeletons";

const ROLES: { value: DashboardRole; label: string; hint: string }[] = [
  { value: "developer", label: "Developer", hint: "API keys, webhooks, logs, playground and docs" },
  { value: "admin", label: "Administrator", hint: "Everything, including settings and the team" },
];

/** Team: the hospital's administrators and developers (admins only). */
export function TeamPage() {
  return (
    <RoleGate roles={["admin"]} what="the team">
      <Team />
    </RoleGate>
  );
}

function Team() {
  const signedIn = useSignedIn();
  const { data, error, loading, reload } = useApi<Staff[]>("staff");
  const [inviting, setInviting] = useState(false);
  const [removing, setRemoving] = useState<Staff | null>(null);
  const toast = useToast();
  const members = (data ?? []).filter((s) => s.role === "admin" || s.role === "developer");

  return (
    <div>
      <PageHeader
        title="Team"
        description="Who can sign in to this dashboard. New members get a temporary password to change at first sign-in, then set up two-step verification."
        actions={
          <button type="button" className={primaryButtonClass} onClick={() => setInviting(true)}>
            <UserPlus className="h-4 w-4" />
            Invite member
          </button>
        }
      />
      {loading && !data && <TeamListSkeleton />}
      {error && <ErrorState message={error.message} onRetry={reload} />}
      {data && (
        <ul className="divide-y divide-neutral-200 rounded-lg border border-neutral-200" data-testid="team">
          {members.map((member) => (
            <li key={member.id} data-testid="team-member" className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-neutral-900">
                  {member.full_name}
                  {member.id === signedIn?.staff.id && <span className="ml-2 text-xs font-normal text-neutral-500">(you)</span>}
                </p>
                <p className="truncate text-xs text-neutral-500">{member.email}</p>
              </div>
              <div className="flex items-center gap-4 text-xs">
                <span className="rounded-full border border-neutral-200 px-2 py-0.5 text-neutral-700">{ROLE_LABELS[member.role]}</span>
                <span className="hidden text-neutral-500 sm:inline">
                  {member.must_change_password ? "Invited" : member.last_login_at ? `Signed in ${timeAgo(member.last_login_at)}` : "Never signed in"}
                </span>
                {member.id !== signedIn?.staff.id && (
                  <button type="button" className="font-medium text-rose-600 hover:underline" onClick={() => setRemoving(member)}>
                    Remove
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {inviting && (
        <Invite
          onClose={() => {
            setInviting(false);
            reload();
          }}
        />
      )}
      {removing && (
        <Remove
          member={removing}
          onClose={() => setRemoving(null)}
          onDone={() => {
            toast(`${removing.full_name} removed`);
            setRemoving(null);
            reload();
          }}
        />
      )}
    </div>
  );
}

function Invite({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<DashboardRole>("developer");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<(Staff & { temporary_password: string }) | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) return setError("Enter their work email.");
    if (name.trim().length < 2) return setError("Enter their full name.");
    setBusy(true);
    try {
      setCreated(
        await apiFetch<Staff & { temporary_password: string }>("staff", {
          method: "POST",
          body: { email: email.trim(), full_name: name.trim(), role },
        })
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not invite them.");
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <Modal title="Member invited" icon="key" onClose={onClose}>
        <div className="flex flex-col gap-4" data-testid="invited">
          <p className="text-sm text-neutral-600">
            Give {created.full_name} this temporary password in person or over a trusted channel. They change it at
            first sign-in, then set up two-step verification.
          </p>
          <CopyField label="Email" value={created.email} testId="invited-email" />
          <CopyField label="Temporary password" value={created.temporary_password} testId="temporary-password" secret />
          <div className="flex justify-end">
            <button type="button" className={primaryButtonClass} onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="Invite a member" icon="person_add" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <div>
          <label htmlFor="member-email" className={labelClass}>
            Email
          </label>
          <input id="member-email" type="email" className={inputClass} value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        </div>
        <div>
          <label htmlFor="member-name" className={labelClass}>
            Full name
          </label>
          <input id="member-name" className={inputClass} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
        </div>
        <fieldset>
          <legend className={labelClass}>Role</legend>
          <div className="flex flex-col gap-2">
            {ROLES.map((option) => (
              <label key={option.value} className="flex cursor-pointer items-start gap-2 rounded-md border border-neutral-200 p-3 text-sm">
                <input type="radio" name="member-role" className="mt-1" checked={role === option.value} onChange={() => setRole(option.value)} />
                <span>
                  <span className="block font-medium text-neutral-900">{option.label}</span>
                  <span className="block text-xs text-neutral-500">{option.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <FormError message={error} />
        <div className="flex justify-end gap-2">
          <button type="button" className={secondaryButtonClass} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className={primaryButtonClass} disabled={busy}>
            {busy ? "Inviting…" : "Invite"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Remove({ member, onClose, onDone }: { member: Staff; onClose: () => void; onDone: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`staff/${member.id}`, { method: "PATCH", body: { active: false } });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove them.");
      setBusy(false);
    }
  }
  return (
    <Modal title={`Remove ${member.full_name}?`} icon="warning" onClose={onClose}>
      <p className="text-sm text-neutral-600">They are signed out everywhere and can no longer sign in.</p>
      <FormError message={error} />
      <div className="flex justify-end gap-2">
        <button type="button" className={secondaryButtonClass} onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button type="button" className={dangerButtonClass} onClick={remove} disabled={busy}>
          Remove
        </button>
      </div>
    </Modal>
  );
}
