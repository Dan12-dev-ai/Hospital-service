"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "@/components/ui/icon";
import { cn } from "cn";
import type { NavItem } from "@/lib/dashboard-types";

export function SidebarLink({ item }: { item: NavItem }) {
  const pathname = usePathname();
  const isActive = pathname === item.href;

  return (
    <Link
      href={item.href}
      className={cn(
        "flex items-center justify-between rounded-2xl px-3.5 py-2.5 text-sm font-medium transition-colors",
        isActive
          ? "bg-pine-green text-white shadow-sm"
          : "text-slate-500 hover:bg-slate-50 hover:text-slate-900"
      )}
    >
      <span className="flex items-center gap-3">
        <Icon
          name={item.icon}
          className={cn(
            "text-[20px]",
            isActive ? "text-white" : "text-slate-400"
          )}
        />
        <span>{item.label}</span>
      </span>
      {item.badge && (
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-[11px] font-semibold",
            isActive
              ? "bg-white/20 text-white"
              : "bg-slate-100 text-slate-600"
          )}
        >
          {item.badge}
        </span>
      )}
      {item.dot && (
        <span className="h-2 w-2 rounded-full bg-emerald-400" />
      )}
    </Link>
  );
}
