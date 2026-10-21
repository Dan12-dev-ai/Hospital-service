"use client";

import { useEffect, useState } from "react";
import { useSidebarMobile } from "@/components/dashboard/sidebar-mobile-context";
import Link from "next/link";
import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import { useSession } from "@/components/session/session-context";
import { navItems } from "@/lib/dashboard-data";
import { initialsOf } from "@/lib/format";
import { SidebarLink } from "@/components/dashboard/sidebar-link";

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const { mobileOpen, setMobileOpen } = useSidebarMobile();

  // Escape closes the mobile drawer.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setMobileOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [setMobileOpen]);

  // Lock body scroll while the mobile drawer is open.
  useEffect(() => {
    if (!mobileOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [mobileOpen]);

  return (
    <>
      {/* Mobile / tablet trigger bar (hidden on xl+ where the rail lives) */}
      <div className="sticky top-0 z-40 flex items-center gap-3 rounded-2xl border border-card-border/80 bg-white p-3 shadow-soft xl:hidden">
        <button
          type="button"
          aria-label="Open navigation menu"
          onClick={() => setMobileOpen(true)}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-50 text-slate-600 transition-colors hover:bg-slate-100"
        >
          <Icon name="menu" className="text-[22px]" />
        </button>
        <Link href="/" className="flex min-w-0 items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-tr from-pine-green to-[#34d399] text-white shadow-md shadow-emerald-900/10">
            <Icon name="local_hospital" className="text-[24px]" />
          </div>
          <div className="flex min-w-0 flex-col text-left">
            <span className="flex items-center gap-1 text-lg font-bold leading-tight tracking-tight text-slate-800">
              Dedan{" "}
              <span className="text-sm font-semibold text-pine-green">OS</span>
            </span>
            <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
              Health Portal
            </span>
          </div>
        </Link>
      </div>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-50 xl:hidden"
          onClick={(event) => {
            // Close the drawer when a nav link (or the backdrop) is clicked.
            if ((event.target as HTMLElement).closest("a")) {
              setMobileOpen(false);
            }
          }}
        >
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setMobileOpen(false)}
            className="absolute inset-0 bg-inverse-surface/40 backdrop-blur-sm"
          />
          <aside className="animate-in fade-in absolute inset-y-0 left-0 flex w-64 max-w-[80vw] flex-col rounded-r-3xl border border-card-border/80 bg-white p-4 shadow-soft slide-in-from-left duration-200">
            <SidebarBody
              collapsed={false}
              onClose={() => setMobileOpen(false)}
            />
          </aside>
        </div>
      )}

      {/* Desktop rail (xl+): sticky, full viewport height, collapsible */}
      <aside
        className={cn(
          "hidden shrink-0 select-none flex-col justify-between rounded-3xl border border-card-border/80 bg-white p-4 shadow-soft transition-[width] duration-200 xl:sticky xl:top-6 xl:flex xl:h-[calc(100vh-3rem)] xl:self-start",
          collapsed ? "xl:w-20" : "xl:w-64"
        )}
      >
        <SidebarBody
          collapsed={collapsed}
          onToggleCollapse={() => setCollapsed((value) => !value)}
        />
      </aside>
    </>
  );
}

function SidebarBody({
  collapsed,
  onToggleCollapse,
  onClose,
}: {
  collapsed: boolean;
  onToggleCollapse?: () => void;
  onClose?: () => void;
}) {
  const session = useSession();
  const staff = session.status === "ready" ? session.staff : null;
  const hospital = session.status === "ready" ? session.hospital : null;
  const items = navItems.filter((item) => !item.roles || (staff !== null && item.roles.includes(staff.role)));
  const [signingOut, setSigningOut] = useState(false);

  return (
    <>
      <div className="flex flex-1 flex-col">
        {/* Logo Branding + collapse / close controls */}
        <div className="mb-4 flex items-center justify-between gap-2 px-1">
          <Link href="/" className="flex min-w-0 items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-tr from-pine-green to-[#34d399] text-white shadow-md shadow-emerald-900/10">
            <Icon name="local_hospital" className="text-[24px]" />
          </div>
          {!collapsed && (
            <div className="flex min-w-0 flex-col">
              <span className="flex items-center gap-1 text-base font-bold leading-tight tracking-tight text-slate-800">
                Dedan{" "}
                <span className="text-xs font-semibold text-pine-green">
                  OS
                </span>
              </span>
              <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">
                Health Portal
              </span>
            </div>
          )}
          </Link>
          <div className="flex items-center gap-1">
            {onClose && (
              <button
                type="button"
                aria-label="Close navigation"
                onClick={onClose}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-50 hover:text-slate-700"
              >
                <Icon name="close" className="text-[18px]" />
              </button>
            )}
            {onToggleCollapse && (
              <button
                type="button"
                aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                onClick={onToggleCollapse}
                className="hidden h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-50 hover:text-slate-700 xl:flex"
              >
                <Icon
                  name={collapsed ? "right_panel_open" : "left_panel_close"}
                  className="text-[18px]"
                />
              </button>
            )}
          </div>
        </div>

        {/* Facility Chip */}
        {!collapsed && (
          <div className="mb-4 flex items-center gap-2.5 rounded-2xl border border-slate-100 bg-slate-50/80 p-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-pine-green">
              <Icon name="domain" className="text-[18px]" />
            </div>
            <div className="flex min-w-0 flex-col">
              <span className="truncate text-[11px] font-semibold text-slate-800">
                {hospital?.name ?? "Loading…"}
              </span>
              <span className="truncate text-[10px] font-medium text-slate-400">
                {hospital?.name_am ?? hospital?.code ?? ""}
              </span>
            </div>
          </div>
        )}

        {/* Navigation Links */}
        <nav className="space-y-0.5">
          {items.map((item) => (
            <SidebarLink
              key={item.href}
              item={item}
              collapsed={collapsed}
            />
          ))}
        </nav>
      </div>

      {/* Bottom User & Sign Out section */}
      <div className="mt-4 shrink-0 space-y-2 border-t border-slate-100 pt-4">
        <div
          className={cn(
            "flex items-center gap-2.5 rounded-2xl border border-slate-100 bg-slate-50/70 p-2",
            collapsed && "justify-center"
          )}
          title={collapsed ? staff?.full_name : undefined}
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-teal-800 text-xs font-bold text-teal-100">
            {staff ? initialsOf(staff.full_name) : "…"}
          </div>
          {!collapsed && (
            <div className="flex min-w-0 flex-col">
              <span className="truncate text-[11px] font-semibold text-slate-800">
                {staff?.full_name ?? ""}
              </span>
              <span className="truncate text-[10px] text-slate-400">
                {staff?.email ?? ""}
              </span>
            </div>
          )}
        </div>
        <button
          type="button"
          disabled={signingOut}
          onClick={async () => {
            setSigningOut(true);
            await session.signOut();
          }}
          title={collapsed ? "Sign Out" : undefined}
          className={cn(
            "flex w-full items-center justify-center gap-2 rounded-2xl border border-red-200/80 bg-red-50/40 px-3 py-2 text-[11px] font-semibold text-rose-600 transition-colors hover:bg-red-50",
            collapsed && "px-0"
          )}
        >
          <Icon name="logout" className="text-[16px]" />
          {!collapsed && <span>Sign Out</span>}
        </button>
      </div>
    </>
  );
}
