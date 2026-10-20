import type { ReactNode } from "react";
import { Icon } from "@/components/ui/icon";

/** The centred card used by the signed-out pages (sign in, sign up). */
export function AuthCard({
  title,
  subtitle,
  children,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div
        className={`w-full ${wide ? "max-w-2xl" : "max-w-md"} rounded-3xl border border-card-border/80 bg-white p-8 shadow-soft`}
      >
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-tr from-pine-green to-[#34d399] text-white shadow-md shadow-emerald-900/10">
            <Icon name="local_hospital" className="text-[24px]" />
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Endod hospital portal</p>
            <h1 className="text-xl font-bold tracking-tight text-slate-900">{title}</h1>
          </div>
        </div>
        {subtitle && <p className="-mt-3 mb-5 text-xs text-slate-500">{subtitle}</p>}
        {children}
      </div>
    </main>
  );
}
