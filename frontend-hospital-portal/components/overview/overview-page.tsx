"use client";

import Link from "next/link";
import { cn } from "cn";
import { ArrowRight, BookOpen, CheckCircle2, Circle, ExternalLink, KeyRound, Rocket, SquareTerminal } from "lucide-react";
import { ErrorState } from "@/components/common/states";
import { PageHeader, Panel } from "@/components/shell/dashboard-shell";
import { useSignedIn } from "@/components/session/session-context";
import { useApi } from "@/lib/api";
import { SWAGGER_URL, timeAgo, type Connection, type ConnectionList } from "@/lib/connect-types";
import { ModeSummarySkeleton } from "@/components/common/page-skeletons";

type Step = { done: boolean; label: string; detail: string; href?: string; action?: string };

/** Overview: where the hospital stands (approval, listing, keys, first calls), and where to go next. */
export function OverviewPage() {
  const signedIn = useSignedIn();
  const { data, error, loading, reload } = useApi<ConnectionList>("connections");
  if (!signedIn) return null;
  const { hospital, staff } = signedIn;
  const isAdmin = staff.role === "admin";
  const keys = data?.items ?? [];
  const test = keys.filter((k) => k.mode === "test");
  const live = keys.filter((k) => k.mode === "live");

  const steps: Step[] = [
    { done: true, label: "Approved by Endod", detail: `${hospital.name} passed Endod's review.` },
    {
      done: hospital.price_in_person !== null,
      label: "Consultation price set",
      detail: "The in-person visit price patients see. Sync it with PUT /prices/consultation, or set it in Settings.",
      href: "/settings",
      action: isAdmin ? "Set it" : undefined,
    },
    {
      done: hospital.latitude !== null && hospital.longitude !== null,
      label: "Location on the map",
      detail: "So patients find the hospital near them.",
      href: "/settings",
      action: isAdmin ? "Set it" : undefined,
    },
    {
      done: hospital.listed,
      label: "Listed in the Endod app",
      detail: hospital.listed ? "Patients can find and book the hospital." : "Hidden from patients until the price and location are set.",
    },
    { done: test.length > 0, label: "Test key created", detail: "Build against Test: nothing is saved.", href: "/keys", action: "Create one" },
    {
      done: test.some((k) => k.last_used_at),
      label: "First test request",
      detail: "Get a token and call the API (or try the Playground).",
      href: "/getting-started",
      action: "Show me how",
    },
    { done: live.length > 0, label: "Live key created", detail: "When you are ready for real patients.", href: "/keys", action: "Create one" },
  ];

  return (
    <div>
      <PageHeader title="Overview" description={`${hospital.name} on Endod: your listing, your keys, and the next step.`} />

      <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
        <Panel title="Checklist" testId="checklist">
          <ol className="flex flex-col">
            {steps.map((step) => (
              <li key={step.label} data-testid="checklist-item" data-done={step.done} className="flex items-start gap-3 border-b border-neutral-100 py-3 last:border-0">
                {step.done ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                ) : (
                  <Circle className="mt-0.5 h-4 w-4 shrink-0 text-neutral-300" />
                )}
                <div className="min-w-0 flex-1">
                  <p className={cn("text-sm", step.done ? "text-neutral-500" : "font-medium text-neutral-900")}>{step.label}</p>
                  {!step.done && <p className="mt-0.5 text-xs text-neutral-500">{step.detail}</p>}
                </div>
                {!step.done && step.href && step.action && (
                  <Link href={step.href} className="shrink-0 text-xs font-medium text-neutral-900 underline underline-offset-2">
                    {step.action}
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </Panel>

        <div className="flex flex-col gap-6">
          <Panel title="Mode" testId="mode-summary">
            {loading && !data && <ModeSummarySkeleton />}
            {error && <ErrorState message={error.message} onRetry={reload} className="p-4" />}
            {data && (
              <dl className="flex flex-col gap-3 text-sm">
                <ModeLine label="Test keys" keys={test} />
                <ModeLine label="Live keys" keys={live} />
              </dl>
            )}
          </Panel>
          <Panel title="Quick links">
            <ul className="flex flex-col gap-1 text-sm">
              <Quick href="/getting-started" icon={Rocket} label="Getting started" />
              <Quick href="/keys" icon={KeyRound} label="API keys" />
              <Quick href="/playground" icon={SquareTerminal} label="Playground" />
              <Quick href="/docs" icon={BookOpen} label="Docs" />
              <li>
                <a href={SWAGGER_URL} target="_blank" rel="noreferrer" className="flex items-center gap-2 rounded px-1 py-1 text-neutral-700 hover:text-neutral-900">
                  <ExternalLink className="h-4 w-4 text-neutral-400" />
                  API reference (Swagger)
                </a>
              </li>
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function ModeLine({ label, keys }: { label: string; keys: Connection[] }) {
  const lastUsed = keys
    .map((k) => k.last_used_at)
    .filter((v): v is string => Boolean(v))
    .sort()
    .pop();
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-neutral-600">{label}</dt>
      <dd className="text-right">
        <span className="font-semibold text-neutral-900" data-testid={`${label.split(" ")[0].toLowerCase()}-keys`}>
          {keys.length}
        </span>
        <span className="block text-[11px] text-neutral-500">{lastUsed ? `used ${timeAgo(lastUsed)}` : "not used yet"}</span>
      </dd>
    </div>
  );
}

function Quick({ href, icon: QuickIcon, label }: { href: string; icon: typeof Rocket; label: string }) {
  return (
    <li>
      <Link href={href} className="group flex items-center gap-2 rounded px-1 py-1 text-neutral-700 hover:text-neutral-900">
        <QuickIcon className="h-4 w-4 text-neutral-400" />
        <span className="flex-1">{label}</span>
        <ArrowRight className="h-3.5 w-3.5 text-neutral-300 group-hover:text-neutral-600" />
      </Link>
    </li>
  );
}
