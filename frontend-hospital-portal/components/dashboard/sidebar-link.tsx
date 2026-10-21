"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "@/components/ui/icon";
import { cn } from "cn";
import type { NavItem } from "@/lib/dashboard-types";

export function SidebarLink({
  item,
  collapsed,
}: {
  item: NavItem;
  collapsed?: boolean;
}) {
  const pathname = usePathname();
  // A patient's page (/patients/<id>) keeps "Patients" highlighted.
  const isActive = pathname === item.href || (item.href !== "/" && pathname.startsWith(`${item.href}/`));

  return (
    <Link
      href={item.href}
      title={collapsed ? item.label : undefined}
      aria-label={item.label}
      className={cn(
        "flex items-center justify-between rounded-xl px-3 py-2 text-[13px] font-medium transition-colors",
        collapsed && "justify-center px-0",
        isActive
          ? "bg-pine-green text-white shadow-sm"
          : "text-slate-500 hover:bg-slate-50 hover:text-slate-900"
      )}
    >
      <span className={cn("flex items-center gap-3", collapsed && "gap-0")}>
        <Icon
          name={item.icon}
          className={cn("text-[20px]", isActive ? "text-white" : "text-slate-400")}
        />
        {!collapsed && <span>{item.label}</span>}
      </span>
      {!collapsed && item.badge && (
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-[11px] font-semibold",
            isActive ? "bg-white/20 text-white" : "bg-slate-100 text-slate-600"
          )}
        >
          {item.badge}
        </span>
      )}
      {!collapsed && item.dot && (
        <span className="h-2 w-2 rounded-full bg-emerald-400" />
      )}
    </Link>
  );
}
