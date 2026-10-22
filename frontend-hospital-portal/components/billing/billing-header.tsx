"use client";

import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";

export function BillingHeader({
  onIssueCard,
}: {
  onIssueCard: () => void;
}) {
  const { showToast } = useDashboard();

  return (
    <header className="flex flex-col justify-between gap-4 border-b border-surface-container pb-6 md:flex-row md:items-center">
      <div>
        <h1 className="text-headline-lg font-headline-lg text-on-surface">
          Card Registration &amp; Billing Directory
        </h1>
        <p className="mt-0.5 text-body-sm font-body-sm text-outline">
          ቅዱስ ጳውሎስ ሆስፒታል
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-2.5">
        <button
          type="button"
          onClick={() =>
            showToast("Filter panel focused: Channel, Clinic & Payment")
          }
          className="flex items-center gap-2 rounded-xl bg-surface-container-lowest px-3.5 py-2 text-label-lg font-label-lg text-on-surface shadow-soft transition-colors hover:bg-surface-container-low"
        >
          <Icon name="tune" className="text-[18px]" />
          <span>Filter View</span>
        </button>
        <button
          type="button"
          onClick={onIssueCard}
          className="flex items-center gap-2 rounded-xl bg-primary-container px-4 py-2 text-label-lg font-label-lg text-on-primary shadow-soft transition-all hover:bg-primary"
        >
          <Icon name="add_card" className="text-[20px]" />
          <span>
            + Issue New Card <span className="font-normal">(አዲስ ካርድ መመዝገቢያ)</span>
          </span>
        </button>
      </div>
    </header>
  );
}
