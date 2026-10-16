"use client";

import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { currentUser, facility, navItems } from "@/lib/dashboard-data";
import { SidebarLink } from "@/components/dashboard/sidebar-link";

export function Sidebar() {
  const { showToast } = useDashboard();

  return (
    <aside className="flex w-full shrink-0 select-none flex-col justify-between rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft xl:w-64">
      <div className="flex flex-col">
        {/* Logo Branding */}
        <div className="mb-6 flex items-center gap-3 px-2 py-1">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-tr from-pine-green to-[#34d399] text-white shadow-md shadow-emerald-900/10">
            <Icon name="local_hospital" className="text-[24px]" />
          </div>
          <div className="flex flex-col">
            <span className="flex items-center gap-1 text-lg font-bold leading-tight tracking-tight text-slate-800">
              Dedan{" "}
              <span className="text-sm font-semibold text-pine-green">OS</span>
            </span>
            <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
              Health Portal
            </span>
          </div>
        </div>

        {/* Facility Chip */}
        <div className="mb-6 flex items-center gap-2.5 rounded-2xl border border-slate-100 bg-slate-50/80 p-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-pine-green">
            <Icon name="domain" className="text-[18px]" />
          </div>
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-xs font-semibold text-slate-800">
              {facility.name}
            </span>
            <span className="truncate text-[10px] font-medium text-slate-400">
              {facility.nameAm}
            </span>
          </div>
        </div>

        {/* Navigation Links */}
        <nav className="space-y-1">
          {navItems.map((item) => (
            <SidebarLink key={item.href} item={item} />
          ))}
        </nav>
      </div>

      {/* Bottom User & Sign Out section */}
      <div className="mt-6 space-y-3 border-t border-slate-100 pt-6">
        <div className="flex items-center gap-3 rounded-2xl border border-slate-100 bg-slate-50/70 p-2">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-teal-800 text-sm font-bold text-teal-100">
            {currentUser.initials}
          </div>
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-xs font-semibold text-slate-800">
              {currentUser.name}
            </span>
            <span className="truncate text-[10px] text-slate-400">
              {currentUser.email}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => showToast("Signing out of Dedan Health OS...")}
          className="flex w-full items-center justify-center gap-2 rounded-2xl border border-red-200/80 bg-red-50/40 px-3 py-2.5 text-xs font-semibold text-rose-600 transition-colors hover:bg-red-50"
        >
          <Icon name="logout" className="text-[16px]" />
          <span>Sign Out</span>
        </button>
      </div>
    </aside>
  );
}
