"use client";

import { useEffect, useState, type ComponentType, type ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "cn";
import {
  Activity,
  BookOpen,
  ExternalLink,
  FileJson,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Menu,
  Rocket,
  Settings,
  SquareTerminal,
  Users,
  Webhook,
  X,
} from "lucide-react";
import { ErrorState } from "@/components/common/states";
import { SessionProvider, useSession } from "@/components/session/session-context";
import { ToastProvider } from "@/components/shell/toast";
import { ROLE_LABELS, type Hospital, type Staff } from "@/lib/api-types";
import { OPENAPI_URL, SWAGGER_URL } from "@/lib/connect-types";
import { initialsOf } from "@/lib/format";
import { DashboardPageSkeleton } from "@/components/common/page-skeletons";

type NavItem = { href: string; label: string; icon: ComponentType<{ className?: string }>; adminOnly?: boolean };

const NAV: { heading?: string; items: NavItem[] }[] = [
  {
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/getting-started", label: "Getting started", icon: Rocket },
    ],
  },
  {
    heading: "Build",
    items: [
      { href: "/keys", label: "API keys", icon: KeyRound },
      { href: "/webhooks", label: "Webhooks", icon: Webhook },
      { href: "/logs", label: "Logs", icon: Activity },
      { href: "/playground", label: "Playground", icon: SquareTerminal },
      { href: "/docs", label: "Docs", icon: BookOpen },
    ],
  },
  {
    heading: "Hospital",
    items: [
      { href: "/settings", label: "Settings", icon: Settings },
      { href: "/team", label: "Team", icon: Users, adminOnly: true },
    ],
  },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * The developer dashboard's frame: a quiet left sidebar (sections, the API
 * reference links, the signed-in person) and the page. It loads the session
 * and shows the page only to administrators and developers of a hospital
 * Endod approved (a hospital still applying is sent to its application by
 * the session; a suspended one sees why).
 */
export function DashboardShell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <SessionProvider>
      <ToastProvider>
        <Frame wide={wide}>{children}</Frame>
      </ToastProvider>
    </SessionProvider>
  );
}

function Frame({ children, wide }: { children: ReactNode; wide: boolean }) {
  const session = useSession();
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const ready = session.status === "ready" ? session : null;
  let body: ReactNode;
  if (session.status === "loading") body = <DashboardPageSkeleton path={pathname} />;
  else if (session.status === "error") body = <ErrorState message={session.error.message} onRetry={session.reload} className="mt-10" />;
  else if (session.hospital.status !== "approved") body = <Suspended hospital={session.hospital} />;
  else body = children;

  return (
    <div className="min-h-screen bg-white text-neutral-900">
      {/* Mobile bar */}
      <div className="sticky top-0 z-30 flex items-center justify-between border-b border-neutral-200 bg-white px-4 py-3 lg:hidden">
        <Brand />
        <button
          type="button"
          aria-label="Open navigation menu"
          onClick={() => setOpen(true)}
          className="rounded-md p-2 text-neutral-600 hover:bg-neutral-100"
        >
          <Menu className="h-5 w-5" />
        </button>
      </div>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-neutral-900/30"
            onClick={() => setOpen(false)}
          />
          <aside
            className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-neutral-200 bg-white"
            onClick={(event) => {
              // A navigation closes the menu.
              if ((event.target as HTMLElement).closest("a")) setOpen(false);
            }}
          >
            <button
              type="button"
              aria-label="Close navigation menu"
              onClick={() => setOpen(false)}
              className="absolute right-3 top-3 rounded-md p-1.5 text-neutral-500 hover:bg-neutral-100"
            >
              <X className="h-4 w-4" />
            </button>
            <SidebarBody staff={ready?.staff ?? null} hospital={ready?.hospital ?? null} pathname={pathname} />
          </aside>
        </div>
      )}
      <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-neutral-200 bg-neutral-50/60 lg:flex">
        <SidebarBody staff={ready?.staff ?? null} hospital={ready?.hospital ?? null} pathname={pathname} />
      </aside>
      <main className="lg:pl-60">
        <div className={cn("mx-auto w-full px-5 py-8 sm:px-8 lg:py-12", wide ? "max-w-6xl" : "max-w-4xl")}>{body}</div>
      </main>
    </div>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2.5">
      <Image src="/endod_logo.jpeg" alt="Endod" width={28} height={28} className="h-7 w-7 rounded-md object-cover" />
      <span className="text-sm font-semibold tracking-tight text-neutral-900">
        Endod <span className="font-normal text-neutral-500">Developers</span>
      </span>
    </Link>
  );
}

function SidebarBody({ staff, hospital, pathname }: { staff: Staff | null; hospital: Hospital | null; pathname: string }) {
  const session = useSession();
  const [signingOut, setSigningOut] = useState(false);
  const isAdmin = staff?.role === "admin";
  return (
    <div className="flex h-full flex-col">
      <div className="px-5 pb-4 pt-5">
        <Brand />
        <p data-testid="hospital-name" className="mt-3 truncate text-xs text-neutral-500" title={hospital?.name}>
          {hospital?.name ?? " "}
        </p>
      </div>
      <nav aria-label="Dashboard" className="flex-1 overflow-y-auto px-3">
        {NAV.map((group, index) => (
          <div key={group.heading ?? index} className="mb-5">
            {group.heading && (
              <p className="mb-1 px-2 text-[11px] font-medium uppercase tracking-wider text-neutral-400">{group.heading}</p>
            )}
            <ul className="space-y-0.5">
              {group.items
                .filter((item) => !item.adminOnly || isAdmin)
                .map((item) => {
                  const active = isActive(pathname, item.href);
                  const ItemIcon = item.icon;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] transition-colors",
                          active
                            ? "bg-white font-medium text-neutral-900 shadow-[0_0_0_1px_rgba(0,0,0,0.06)]"
                            : "text-neutral-600 hover:bg-white hover:text-neutral-900"
                        )}
                      >
                        <ItemIcon className={cn("h-4 w-4", active ? "text-neutral-900" : "text-neutral-400")} />
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
            </ul>
          </div>
        ))}
        <div className="mb-5">
          <p className="mb-1 px-2 text-[11px] font-medium uppercase tracking-wider text-neutral-400">API reference</p>
          <ul className="space-y-0.5">
            <li>
              <a
                href={SWAGGER_URL}
                target="_blank"
                rel="noreferrer"
                data-testid="swagger-link"
                className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] text-neutral-600 hover:bg-white hover:text-neutral-900"
              >
                <ExternalLink className="h-4 w-4 text-neutral-400" />
                Swagger
              </a>
            </li>
            <li>
              <a
                href={OPENAPI_URL}
                target="_blank"
                rel="noreferrer"
                data-testid="openapi-link"
                className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] text-neutral-600 hover:bg-white hover:text-neutral-900"
              >
                <FileJson className="h-4 w-4 text-neutral-400" />
                openapi.json
              </a>
            </li>
          </ul>
        </div>
      </nav>
      <div className="border-t border-neutral-200 p-3">
        <div className="flex items-center gap-2.5 px-2 py-1.5">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-neutral-900 text-[11px] font-semibold text-white">
            {staff ? initialsOf(staff.full_name) : ""}
          </div>
          <div className="min-w-0 flex-1">
            <p data-testid="signed-in-name" className="truncate text-xs font-medium text-neutral-900">
              {staff?.full_name ?? ""}
            </p>
            <p data-testid="signed-in-email" className="truncate text-[11px] text-neutral-500">
              {staff ? `${ROLE_LABELS[staff.role] ?? staff.role} · ${staff.email}` : ""}
            </p>
          </div>
          <button
            type="button"
            title="Sign out"
            aria-label="Sign out"
            disabled={signingOut}
            onClick={async () => {
              setSigningOut(true);
              await session.signOut();
            }}
            className="rounded-md p-1.5 text-neutral-500 hover:bg-neutral-100 hover:text-neutral-900"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
        <Link href="/account/password" className="mt-1 block px-2 text-[11px] text-neutral-500 hover:text-neutral-900">
          Change password
        </Link>
      </div>
    </div>
  );
}

function Suspended({ hospital }: { hospital: Hospital }) {
  return (
    <div data-testid="hospital-status-banner" data-status={hospital.status} className="mt-10 rounded-lg border border-rose-200 bg-rose-50 p-6">
      <h1 className="text-base font-semibold text-rose-900">{hospital.name} is suspended by Endod</h1>
      <p className="mt-2 text-sm text-rose-800">
        Its API keys stop working and patients cannot find it in the Endod app until Endod lifts the suspension.
        Contact Endod for details.
      </p>
    </div>
  );
}

/** A page's title, a line about it, and its main actions. */
export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-neutral-900">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-sm leading-6 text-neutral-500">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** A bordered section with a heading, the dashboard's basic block. */
export function Panel({
  title,
  description,
  actions,
  children,
  className,
  testId,
}: {
  title?: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <section data-testid={testId} className={cn("rounded-lg border border-neutral-200 bg-white", className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-neutral-200 px-5 py-4">
          <div>
            {title && <h2 className="text-sm font-semibold text-neutral-900">{title}</h2>}
            {description && <p className="mt-0.5 text-xs leading-5 text-neutral-500">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}
