import type { CSSProperties, ReactNode } from "react";
import { cn } from "cn";

/**
 * Skeletons: while a page or a section loads, grey blocks shaped like what is
 * coming (headings, cards, tables, form fields) instead of a spinner. The
 * shimmer is in app/globals.css (.skeleton) and stops for people who ask for
 * less motion. Screen readers hear one "Loading…" per region (role=status,
 * aria-busy); the blocks themselves are hidden from them.
 */

/** One grey block. Size and shape it with classes (h-*, w-*, rounded-*). */
export function Skeleton({ className, style }: { className?: string; style?: CSSProperties }) {
  return (
    <div aria-hidden="true" data-skeleton-block="" className={cn("skeleton rounded-md", className)} style={style} />
  );
}

/** A region that is loading: busy for assistive technology, announced once by `label`. */
export function SkeletonRegion({
  label = "Loading…",
  className,
  children,
  testId = "skeleton",
}: {
  label?: string;
  className?: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <div role="status" aria-busy="true" aria-live="polite" data-testid={testId} className={className}>
      <span className="sr-only">{label}</span>
      <div aria-hidden="true">{children}</div>
    </div>
  );
}

const LINE_WIDTHS = ["100%", "92%", "84%", "96%", "72%"];

/** Lines of text (the last one shorter, as a paragraph ends). */
export function SkeletonText({
  lines = 3,
  className,
  lineClassName = "h-3",
  lastWidth = "60%",
}: {
  lines?: number;
  className?: string;
  lineClassName?: string;
  lastWidth?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          className={lineClassName}
          style={{ width: index === lines - 1 && lines > 1 ? lastWidth : LINE_WIDTHS[index % LINE_WIDTHS.length] }}
        />
      ))}
    </div>
  );
}

/** A labelled form field: the label, then the input. */
export function SkeletonField({
  className,
  inputClassName = "h-10 rounded-xl",
}: {
  className?: string;
  inputClassName?: string;
}) {
  return (
    <div className={className}>
      <Skeleton className="mb-1.5 h-3 w-24" />
      <Skeleton className={cn("w-full", inputClassName)} />
    </div>
  );
}

/** Several fields in a grid (one column on phones). */
export function SkeletonFields({
  count = 4,
  columns = 2,
  className,
  inputClassName,
}: {
  count?: number;
  columns?: 1 | 2;
  className?: string;
  inputClassName?: string;
}) {
  return (
    <div className={cn("grid grid-cols-1 gap-4", columns === 2 && "sm:grid-cols-2", className)}>
      {Array.from({ length: count }, (_, index) => (
        <SkeletonField key={index} inputClassName={inputClassName} />
      ))}
    </div>
  );
}

/** The dashboard's page header (components/shell/dashboard-shell.tsx PageHeader). */
export function SkeletonPageHeader({
  action = false,
  descriptionLines = 2,
}: {
  action?: boolean;
  descriptionLines?: number;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 flex-1">
        <Skeleton className="h-7 w-44" />
        {descriptionLines > 0 && (
          <SkeletonText lines={descriptionLines} className="mt-3 max-w-2xl" lineClassName="h-3.5" />
        )}
      </div>
      {action && <Skeleton className="h-8 w-32 rounded-xl" />}
    </div>
  );
}

/** The dashboard's bordered panel: a title bar, then its body (lines by default). */
export function SkeletonPanel({
  title = true,
  action = false,
  rows = 3,
  className,
  children,
}: {
  title?: boolean;
  action?: boolean;
  rows?: number;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div className={cn("rounded-lg border border-neutral-200 bg-white", className)}>
      {title && (
        <div className="flex items-center justify-between gap-3 border-b border-neutral-200 px-5 py-4">
          <Skeleton className="h-4 w-36" />
          {action && <Skeleton className="h-3.5 w-16" />}
        </div>
      )}
      <div className="px-5 py-4">{children ?? <SkeletonText lines={rows} />}</div>
    </div>
  );
}

/** A table: a header row, then rows of cells. */
export function SkeletonTable({
  rows = 5,
  columns = 5,
  className,
}: {
  rows?: number;
  columns?: number;
  className?: string;
}) {
  const widths = ["w-24", "w-40", "w-12", "w-16", "w-20", "w-28"];
  return (
    <div className={cn("flex flex-col", className)}>
      <div className="flex gap-6 pb-2.5">
        {Array.from({ length: columns }, (_, c) => (
          <Skeleton key={c} className={cn("h-3", widths[c % widths.length], c === 1 && "flex-1")} />
        ))}
      </div>
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex gap-6 border-t border-neutral-100 py-2.5">
          {Array.from({ length: columns }, (_, c) => (
            <Skeleton key={c} className={cn("h-3", widths[c % widths.length], c === 1 && "flex-1")} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** A bordered list of rows: two lines on the left, a badge and an action on the right. */
export function SkeletonList({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <ul className={cn("divide-y divide-neutral-200 rounded-lg border border-neutral-200", className)}>
      {Array.from({ length: rows }, (_, index) => (
        <li key={index} className="flex items-center justify-between gap-4 px-5 py-4">
          <div className="min-w-0 flex-1">
            <Skeleton className="h-4 w-48 max-w-full" />
            <Skeleton className="mt-2 h-3 w-64 max-w-full" />
          </div>
          <div className="flex items-center gap-3">
            <Skeleton className="h-5 w-14 rounded-full" />
            <Skeleton className="hidden h-3 w-20 sm:block" />
          </div>
        </li>
      ))}
    </ul>
  );
}
