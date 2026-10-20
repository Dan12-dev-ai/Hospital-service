"use client";

import type { ReactNode } from "react";
import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import { useSession } from "@/components/session/session-context";
import type { Role } from "@/lib/api-types";

/** Marks a page or card whose numbers are illustrative, not from the hospital service. */
export function SampleBadge({ className, label = "Sample data" }: { className?: string; label?: string }) {
  return (
    <span
      data-testid="sample-badge"
      title="Illustrative data: this module is not connected to the hospital service yet."
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800",
        className
      )}
    >
      <Icon name="science" className="text-[12px]" />
      {label}
    </span>
  );
}

/** A strip above a page that is entirely sample data. */
export function SamplePageNotice({ module }: { module: string }) {
  return (
    <div className="flex items-center gap-2 rounded-2xl border border-amber-200 bg-amber-50/70 px-4 py-2.5 text-xs text-amber-900">
      <SampleBadge />
      <span>
        {module} is not connected to the hospital service yet. Everything on this page is illustrative.
      </span>
    </div>
  );
}

export function LoadingState({ label = "Loading…", className }: { label?: string; className?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex items-center justify-center gap-2 rounded-2xl bg-surface-container-lowest p-10 text-sm text-outline shadow-soft",
        className
      )}
    >
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-pine-green border-t-transparent" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
  className,
}: {
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      data-testid="error-state"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-2xl border border-rose-100 bg-rose-50/60 p-8 text-center text-sm text-rose-800",
        className
      )}
    >
      <Icon name="error" className="text-[28px] text-rose-500" />
      <p>{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-xl bg-white px-4 py-1.5 text-xs font-semibold text-rose-700 shadow-sm hover:bg-rose-100"
        >
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ icon = "inbox", title, children }: { icon?: string; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 p-10 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-pine-light text-pine-green">
        <Icon name={icon} className="text-[24px]" />
      </div>
      <p className="text-sm font-semibold text-slate-800">{title}</p>
      {children && <div className="max-w-md text-xs text-slate-500">{children}</div>}
    </div>
  );
}

export function NoAccess({ what }: { what: string }) {
  return (
    <div
      data-testid="no-access"
      className="flex flex-col items-center justify-center gap-2 rounded-3xl border border-card-border/80 bg-white p-14 text-center shadow-soft"
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 text-slate-500">
        <Icon name="lock" className="text-[24px]" />
      </div>
      <h1 className="text-lg font-bold text-slate-900">No access</h1>
      <p className="max-w-md text-xs text-slate-500">Your role does not give access to {what}. Ask an administrator if you need it.</p>
    </div>
  );
}

/**
 * Renders `children` once the session is known and the staff member's role
 * is one of `roles`; otherwise a loading, error or no-access state.
 */
export function RoleGate({ roles, what, children }: { roles: Role[] | "any"; what: string; children: ReactNode }) {
  const session = useSession();
  if (session.status === "loading") return <LoadingState />;
  if (session.status === "error") return <ErrorState message={session.error.message} onRetry={session.reload} />;
  if (roles !== "any" && !roles.includes(session.staff.role)) return <NoAccess what={what} />;
  return <>{children}</>;
}

export function Modal({
  title,
  icon,
  onClose,
  children,
  footer,
}: {
  title: string;
  icon?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/40 p-4 backdrop-blur-sm"
    >
      <div className="flex max-h-[90vh] w-full max-w-lg flex-col gap-4 overflow-y-auto rounded-3xl bg-surface-container-lowest p-6 shadow-2xl">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            {icon && (
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary text-on-primary">
                <Icon name={icon} className="text-[18px]" />
              </div>
            )}
            <h2 className="text-base font-bold text-on-surface">{title}</h2>
          </div>
          <button
            type="button"
            aria-label="Close dialog"
            onClick={onClose}
            className="text-outline transition-colors hover:text-on-surface"
          >
            <Icon name="close" className="text-[20px]" />
          </button>
        </div>
        {children}
        {footer && <div className="flex items-center justify-end gap-2 pt-1">{footer}</div>}
      </div>
    </div>
  );
}

export const inputClass =
  "w-full rounded-xl bg-surface-container-low px-3.5 py-2.5 text-sm text-on-surface placeholder:text-outline focus:outline-none focus:ring-2 focus:ring-primary-container disabled:opacity-60";

export const labelClass = "mb-1 block text-xs font-semibold text-on-surface-variant";

export const primaryButtonClass =
  "inline-flex items-center justify-center gap-1.5 rounded-xl bg-primary-container px-4 py-2 text-xs font-semibold text-on-primary shadow-sm transition-colors hover:bg-pine-dark disabled:cursor-not-allowed disabled:opacity-60";

export const secondaryButtonClass =
  "inline-flex items-center justify-center gap-1.5 rounded-xl bg-surface-container px-4 py-2 text-xs font-semibold text-on-surface-variant transition-colors hover:bg-surface-container-high disabled:cursor-not-allowed disabled:opacity-60";

export const dangerButtonClass =
  "inline-flex items-center justify-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60";

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" data-testid="form-error" className="rounded-xl bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700">
      {message}
    </p>
  );
}
