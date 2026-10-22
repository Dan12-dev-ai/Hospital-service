"use client";

import { useState } from "react";
import Link from "next/link";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { useSession } from "@/components/session/session-context";

/** The signed-in staff member, with change-password and sign-out. */
function ProfileChip() {
  const session = useSession();
  const [signingOut, setSigningOut] = useState(false);

  return (
    <div className="flex items-center gap-2">
      <Link
        href="/account/password"
        title="Change password"
        aria-label="Change password"
        className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-50 text-slate-600 transition-colors hover:bg-slate-100"
      >
        <Icon name="key" className="text-[19px]" />
      </Link>
      <button
        type="button"
        disabled={signingOut}
        onClick={async () => {
          setSigningOut(true);
          await session.signOut();
        }}
        className="flex items-center gap-1.5 rounded-full border border-red-200/80 bg-red-50/40 px-3 py-1.5 text-[11px] font-semibold text-rose-600 transition-colors hover:bg-red-50 disabled:opacity-60"
      >
        <Icon name="logout" className="text-[16px]" />
        <span>{signingOut ? "Signing out…" : "Sign out"}</span>
      </button>
    </div>
  );
}

export function TopBar() {
  const { searchQuery, setSearchQuery, showToast } = useDashboard();

  return (
    <header data-testid="top-bar" className="flex flex-col items-center justify-between gap-4 rounded-3xl border border-card-border/80 bg-white px-6 py-3.5 shadow-soft md:flex-row">
      {/* Search Input */}
      <div className="relative flex w-full items-center md:w-96">
        <Icon
          name="search"
          className="absolute left-3.5 text-[18px] text-slate-400"
        />
        <input
          type="text"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          placeholder="Search Patient by Name, MRN or Digital Health ID..."
          className="w-full rounded-full border border-transparent bg-slate-50 py-2 pl-10 pr-4 text-xs text-slate-700 placeholder-slate-400 transition-all focus:border-pine-green focus:bg-white focus:outline-none"
        />
      </div>

      {/* Action items & User Profile */}
      <div className="flex items-center gap-3 self-end md:self-auto">
        {/* Bilingual Switcher */}
        <button
          type="button"
          title="Switch Language"
          onClick={() => showToast("Switching portal language to አማርኛ...")}
          className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-100"
        >
          <Icon name="translate" className="text-[16px] text-pine-green" />
          <span className="text-[11px] font-semibold">EN | አማርኛ</span>
        </button>

        <ProfileChip />
      </div>
    </header>
  );
}
