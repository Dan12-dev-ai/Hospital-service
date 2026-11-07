import type { ReactNode } from "react";
import { cn } from "cn";
import {
  Skeleton,
  SkeletonField,
  SkeletonFields,
  SkeletonList,
  SkeletonPageHeader,
  SkeletonPanel,
  SkeletonRegion,
  SkeletonTable,
  SkeletonText,
} from "@/components/common/skeleton";

/**
 * The dashboard's pages as skeletons: what each page looks like while its
 * data (or the session) loads. The page components use the parts (the body
 * under a header they already show); the shell uses the whole page while it
 * loads the session (DashboardPageSkeleton).
 */

// --- parts the pages use under their own header -------------------------------------------

/** API keys: the key list and the URLs under it. */
export function KeysListSkeleton() {
  return (
    <SkeletonRegion label="Loading your keys…">
      <SkeletonList rows={3} />
      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index}>
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-2 h-3.5 w-56 max-w-full" />
          </div>
        ))}
      </div>
    </SkeletonRegion>
  );
}

/** The API key picker of Webhooks and Logs, then what the page shows for the key. */
export function KeyPickerSkeleton({ children }: { children: ReactNode }) {
  return (
    <SkeletonRegion label="Loading your keys…">
      <div className="flex flex-col gap-6">
        <SkeletonField className="max-w-sm" />
        {children}
      </div>
    </SkeletonRegion>
  );
}

/** A panel holding a log table (Logs' requests, Webhooks' deliveries). */
export function LogTableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <SkeletonRegion label="Loading…">
      <SkeletonTable rows={rows} columns={5} />
    </SkeletonRegion>
  );
}

export function WebhookBodySkeleton() {
  return (
    <>
      <SkeletonPanel>
        <SkeletonField />
        <div className="mt-4 flex gap-2">
          <Skeleton className="h-8 w-20 rounded-xl" />
          <Skeleton className="h-8 w-32 rounded-xl" />
        </div>
      </SkeletonPanel>
      <SkeletonPanel action>
        <SkeletonTable rows={4} columns={5} />
      </SkeletonPanel>
    </>
  );
}

export function LogsBodySkeleton() {
  return (
    <SkeletonPanel action>
      <SkeletonTable rows={6} columns={5} />
    </SkeletonPanel>
  );
}

/** Overview's "Mode" panel: two lines of key counts. */
export function ModeSummarySkeleton() {
  return (
    <SkeletonRegion label="Loading your keys…">
      <div className="flex flex-col gap-3">
        {[0, 1].map((index) => (
          <div key={index} className="flex items-baseline justify-between gap-2">
            <Skeleton className="h-3.5 w-20" />
            <div className="flex flex-col items-end gap-1.5">
              <Skeleton className="h-4 w-6" />
              <Skeleton className="h-2.5 w-16" />
            </div>
          </div>
        ))}
      </div>
    </SkeletonRegion>
  );
}

/** Playground's console: the request form and the answer. */
export function PlaygroundConsoleSkeleton() {
  return (
    <SkeletonRegion label="Loading the API reference…">
      <PlaygroundConsoleBlocks />
    </SkeletonRegion>
  );
}

function PlaygroundConsoleBlocks() {
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <SkeletonPanel>
        <div className="flex flex-col gap-4">
          <SkeletonField />
          <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2">
            <SkeletonField />
            <SkeletonField />
          </div>
          <SkeletonField />
          <SkeletonField inputClassName="h-48 rounded-xl" />
          <Skeleton className="h-8 w-28 rounded-xl" />
        </div>
      </SkeletonPanel>
      <SkeletonPanel>
        <Skeleton className="h-64 w-full rounded-lg" />
      </SkeletonPanel>
    </div>
  );
}

/** Docs: the section list on the left, the page on the right. */
export function DocsBodySkeleton() {
  return (
    <SkeletonRegion label="Loading the docs…">
      <DocsBlocks />
    </SkeletonRegion>
  );
}

function DocsBlocks() {
  return (
    <div className="grid gap-10 lg:grid-cols-[200px_minmax(0,1fr)]">
      <div className="hidden flex-col gap-5 lg:flex">
        {[5, 4, 3].map((count, group) => (
          <div key={group}>
            <Skeleton className="mb-2.5 h-2.5 w-20" />
            <div className="flex flex-col gap-2 border-l border-neutral-200 pl-3">
              {Array.from({ length: count }, (_, index) => (
                <Skeleton key={index} className="h-3" style={{ width: `${60 + ((index * 13) % 35)}%` }} />
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="min-w-0">
        <Skeleton className="h-8 w-2/3" />
        <SkeletonText lines={4} className="mt-6" lineClassName="h-3.5" />
        <Skeleton className="mt-6 h-6 w-1/3" />
        <SkeletonText lines={3} className="mt-4" lineClassName="h-3.5" />
        <Skeleton className="mt-6 h-36 w-full rounded-lg" />
        <SkeletonText lines={3} className="mt-6" lineClassName="h-3.5" />
      </div>
    </div>
  );
}

/** Team: the members. */
export function TeamListSkeleton() {
  return (
    <SkeletonRegion label="Loading the team…">
      <SkeletonList rows={3} />
    </SkeletonRegion>
  );
}

/** Settings: the listing status and the sections of fields. */
export function SettingsFormSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-lg border border-neutral-200 px-5 py-4">
        <Skeleton className="h-4 w-64 max-w-full" />
        <Skeleton className="mt-3 h-3 w-48" />
      </div>
      {[6, 3, 2].map((count, index) => (
        <div key={index} className="rounded-lg border border-neutral-200 bg-white p-5">
          <Skeleton className="mb-4 h-4 w-32" />
          <SkeletonFields count={count} />
        </div>
      ))}
    </div>
  );
}

/** Settings: the synced price list (three category tables). */
export function PriceListSkeleton() {
  return (
    <SkeletonRegion label="Loading the price list…" className="mt-4">
      <div className="flex flex-col gap-6">
        {[0, 1, 2].map((index) => (
          <div key={index} className="rounded-lg border border-neutral-200">
            <div className="flex items-center justify-between border-b border-neutral-200 px-5 py-3">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-3 w-32" />
            </div>
            <div className="px-5 py-3">
              <SkeletonTable rows={2} columns={4} />
            </div>
          </div>
        ))}
      </div>
    </SkeletonRegion>
  );
}

// --- whole pages (the shell, while the session loads) -----------------------------------------

function OverviewSkeleton() {
  return (
    <>
      <SkeletonPageHeader descriptionLines={1} />
      <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
        <SkeletonPanel>
          <div className="flex flex-col">
            {Array.from({ length: 7 }, (_, index) => (
              <div key={index} className="flex items-start gap-3 border-b border-neutral-100 py-3 last:border-0">
                <Skeleton className="mt-0.5 h-4 w-4 shrink-0 rounded-full" />
                <div className="flex-1">
                  <Skeleton className="h-3.5 w-48 max-w-full" />
                  <Skeleton className="mt-1.5 h-3 w-72 max-w-full" />
                </div>
              </div>
            ))}
          </div>
        </SkeletonPanel>
        <div className="flex flex-col gap-6">
          <SkeletonPanel rows={2} />
          <SkeletonPanel rows={5} />
        </div>
      </div>
    </>
  );
}

function GettingStartedSkeleton() {
  return (
    <>
      <SkeletonPageHeader />
      <div className="flex flex-col gap-10">
        {[0, 1, 2].map((index) => (
          <div key={index} className="flex gap-4">
            <Skeleton className="h-7 w-7 shrink-0 rounded-full" />
            <div className="min-w-0 flex-1">
              <Skeleton className="h-4 w-56 max-w-full" />
              <SkeletonText lines={2} className="mt-3" />
              <Skeleton className="mt-3 h-20 w-full rounded-lg" />
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

function PageSkeleton({ path }: { path: string }) {
  const section = path.split("/")[1] ?? "";
  switch (section) {
    case "":
      return <OverviewSkeleton />;
    case "getting-started":
      return <GettingStartedSkeleton />;
    case "keys":
      return (
        <>
          <SkeletonPageHeader action />
          <SkeletonList rows={3} />
        </>
      );
    case "webhooks":
      return (
        <>
          <SkeletonPageHeader />
          <div className="flex flex-col gap-6">
            <SkeletonField className="max-w-sm" />
            <WebhookBodySkeleton />
          </div>
        </>
      );
    case "logs":
      return (
        <>
          <SkeletonPageHeader />
          <div className="flex flex-col gap-6">
            <SkeletonField className="max-w-sm" />
            <LogsBodySkeleton />
          </div>
        </>
      );
    case "playground":
      return (
        <>
          <SkeletonPageHeader action />
          <PlaygroundConsoleBlocks />
        </>
      );
    case "docs":
      return <DocsBlocks />;
    case "settings":
      return (
        <>
          <SkeletonPageHeader action descriptionLines={1} />
          <SettingsFormSkeleton />
        </>
      );
    case "team":
      return (
        <>
          <SkeletonPageHeader action />
          <SkeletonList rows={3} />
        </>
      );
    default:
      return (
        <>
          <SkeletonPageHeader />
          <SkeletonPanel rows={4} />
        </>
      );
  }
}

/** The page at `path` as a skeleton (the shell shows it while it loads the session). */
export function DashboardPageSkeleton({ path, className }: { path: string; className?: string }) {
  return (
    <SkeletonRegion label="Loading…" className={className} testId="page-skeleton">
      <PageSkeleton path={path} />
    </SkeletonRegion>
  );
}

/** The whole dashboard (sidebar and page), for a route that streams in before its shell. */
export function DashboardFrameSkeleton({ path, wide = false }: { path: string; wide?: boolean }) {
  return (
    <div className="min-h-screen bg-white">
      <aside
        className="fixed inset-y-0 left-0 hidden w-60 flex-col gap-6 border-r border-neutral-200 bg-neutral-50/60 px-5 py-5 lg:flex"
        aria-hidden="true"
      >
        <div className="flex items-center gap-2.5">
          <Skeleton className="h-7 w-7" />
          <Skeleton className="h-4 w-32" />
        </div>
        {[2, 5, 2].map((count, group) => (
          <div key={group} className="flex flex-col gap-2.5">
            {Array.from({ length: count }, (_, index) => (
              <Skeleton key={index} className="h-3.5 w-28" />
            ))}
          </div>
        ))}
      </aside>
      <main className="lg:pl-60">
        <div className={cn("mx-auto w-full px-5 py-8 sm:px-8 lg:py-12", wide ? "max-w-6xl" : "max-w-4xl")}>
          <DashboardPageSkeleton path={path} />
        </div>
      </main>
    </div>
  );
}

/** A signed-out card's form (change password, two-step set-up) while it loads. */
export function AuthFormSkeleton({
  fields = 3,
  label = "Loading…",
  media = false,
}: {
  fields?: number;
  label?: string;
  media?: boolean;
}) {
  return (
    <SkeletonRegion label={label}>
      <div className="space-y-4">
        <SkeletonText lines={2} />
        {media && <Skeleton className="mx-auto h-[220px] w-[220px] rounded-lg" />}
        {Array.from({ length: fields }, (_, index) => (
          <SkeletonField key={index} />
        ))}
        <Skeleton className="h-10 w-full rounded-xl" />
      </div>
    </SkeletonRegion>
  );
}

/** The printable setup guide of one key. */
export function SetupGuideSkeleton() {
  return (
    <SkeletonRegion label="Preparing the setup guide…" className="mx-auto max-w-3xl p-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-2 h-7 w-72 max-w-full" />
        </div>
        <Skeleton className="h-8 w-40 rounded-xl" />
      </div>
      <div className="flex flex-col">
        {Array.from({ length: 10 }, (_, index) => (
          <div key={index} className="flex gap-4 border-t border-slate-200 py-2.5">
            <Skeleton className="h-3.5 w-48 shrink-0" />
            <Skeleton className="h-3.5 flex-1" />
          </div>
        ))}
      </div>
    </SkeletonRegion>
  );
}
