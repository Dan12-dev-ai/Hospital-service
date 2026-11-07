import { Skeleton, SkeletonField, SkeletonRegion, SkeletonText } from "@/components/common/skeleton";

/**
 * The onboarding pages as skeletons (components/common/skeleton.tsx): shown
 * inside the onboarding card while the application, the Under review status
 * or the demo calendar loads, in the shape of what is coming.
 */

/** "Step n of m", the progress bar and the step names. */
function ProgressSkeleton({ steps }: { steps: number }) {
  return (
    <div className="mb-7">
      <div className="mb-2 flex items-center justify-between">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-3 w-8" />
      </div>
      <Skeleton className="h-1.5 w-full rounded-full" />
      <div className="mt-3 hidden gap-1 sm:grid" style={{ gridTemplateColumns: `repeat(${steps}, minmax(0, 1fr))` }}>
        {Array.from({ length: steps }, (_, index) => (
          <Skeleton key={index} className="mx-auto h-2.5 w-12" />
        ))}
      </div>
    </div>
  );
}

/** A step's heading and hint. */
function HeadingSkeleton() {
  return (
    <div className="mb-5">
      <Skeleton className="h-9 w-64 max-w-full rounded-lg" />
      <Skeleton className="mt-2.5 h-3 w-80 max-w-full" />
    </div>
  );
}

/** Back on the left, the step's action on the right. */
function NavSkeleton() {
  return (
    <div className="mt-7 flex items-center justify-between gap-3">
      <Skeleton className="h-4 w-12" />
      <Skeleton className="h-11 w-32 rounded-full" />
    </div>
  );
}

const FIELD = "h-11 rounded-xl";

/** A step of the wizard: heading, two choice cards, fields, the navigation. */
export function OnboardingStepSkeleton({ fields = 6, progress = 0 }: { fields?: number; progress?: number }) {
  return (
    <SkeletonRegion label="Loading your application…" testId="onboarding-skeleton">
      {progress > 0 && <ProgressSkeleton steps={progress} />}
      <HeadingSkeleton />
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2.5">
          <Skeleton className="h-14 rounded-xl" />
          <Skeleton className="h-14 rounded-xl" />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {Array.from({ length: fields }, (_, index) => (
            <SkeletonField key={index} inputClassName={FIELD} />
          ))}
        </div>
      </div>
      <NavSkeleton />
    </SkeletonRegion>
  );
}

/** The Under review page: the facility, the status, the demo and what happens next. */
export function UnderReviewSkeleton() {
  return (
    <SkeletonRegion label="Loading your application's status…" testId="onboarding-skeleton">
      <div className="mb-5 flex items-center gap-3">
        <Skeleton className="h-12 w-12 shrink-0 rounded-2xl" />
        <div className="flex-1">
          <Skeleton className="h-2.5 w-28" />
          <Skeleton className="mt-2 h-8 w-64 max-w-full rounded-lg" />
        </div>
      </div>
      <div className="mb-5 rounded-2xl bg-[#F8FAFB] p-4">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-2 h-4 w-72 max-w-full" />
        <Skeleton className="mt-3 h-8 w-28 rounded-full" />
      </div>
      <Skeleton className="mb-3 h-4 w-40" />
      <div className="space-y-3">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="flex items-start gap-3">
            <Skeleton className="h-8 w-8 shrink-0 rounded-full" />
            <SkeletonText lines={1} className="flex-1 pt-2" />
          </div>
        ))}
      </div>
    </SkeletonRegion>
  );
}

/** The demo calendar: the weekdays, the weeks, then the times of a day. */
export function DemoCalendarSkeleton() {
  return (
    <SkeletonRegion label="Loading the calendar…" testId="demo-skeleton">
      <div className="space-y-5">
        <div>
          <div className="mb-2 grid grid-cols-5 gap-1.5">
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="mx-auto h-2.5 w-8" />
            ))}
          </div>
          <div className="grid grid-cols-5 gap-1.5">
            {Array.from({ length: 20 }, (_, index) => (
              <Skeleton key={index} className="h-14 rounded-xl" />
            ))}
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {Array.from({ length: 8 }, (_, index) => (
            <Skeleton key={index} className="h-10 rounded-xl" />
          ))}
        </div>
      </div>
    </SkeletonRegion>
  );
}

/** The map of the location step while Leaflet loads. */
export function MapSkeleton() {
  return (
    <SkeletonRegion label="Loading the map…" testId="map-skeleton">
      <Skeleton className="h-64 w-full rounded-2xl sm:h-72" />
    </SkeletonRegion>
  );
}
