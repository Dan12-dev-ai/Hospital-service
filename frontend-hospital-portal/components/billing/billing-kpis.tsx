import { Icon } from "@/components/ui/icon";

type BillingKpi = {
  label: string;
  badge?: { text: string; className: string };
  value: string;
  valueClassName?: string;
  icon: string;
  iconBoxClassName: string;
};

const billingKpis: BillingKpi[] = [
  {
    label: "Total Cards Issued",
    value: "482",
    icon: "badge",
    iconBoxClassName: "bg-surface-container-low text-black",
  },
  {
    label: "In-Person Desk",
    badge: { text: "ETB 15,900", className: "bg-surface-container text-black" },
    value: "318",
    icon: "desk",
    iconBoxClassName: "bg-surface-container-low text-black",
  },
  {
    label: "Mobile Self-Reg",
    badge: {
      text: "Telebirr / CBE",
      className: "bg-neutral-200 text-neutral-800",
    },
    value: "164",
    icon: "phone_iphone",
    iconBoxClassName: "bg-neutral-200 text-neutral-800",
  },
  {
    label: "Pending Activation",
    badge: {
      text: "Review Needed",
      className: "bg-error-container text-on-error-container",
    },
    value: "19",
    valueClassName: "text-error",
    icon: "pending_actions",
    iconBoxClassName: "bg-error-container text-on-error-container",
  },
];

export function BillingKpis() {
  return (
    <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {billingKpis.map((kpi) => (
        <div
          key={kpi.label}
          className="flex items-center justify-between rounded-2xl bg-surface-container-lowest p-4 shadow-soft"
        >
          <div className="flex flex-col">
            <div className="flex items-center gap-1.5">
              <span className="text-label-md font-label-md text-outline">
                {kpi.label}
              </span>
              {kpi.badge && (
                <span
                  className={`rounded px-1.5 py-0.5 text-label-sm font-label-sm ${kpi.badge.className}`}
                >
                  {kpi.badge.text}
                </span>
              )}
            </div>
            <span
              className={`mt-1 text-metric-display font-metric-display ${kpi.valueClassName ?? "text-on-surface"}`}
            >
              {kpi.value}
            </span>
          </div>
          <div
            className={`flex h-12 w-12 items-center justify-center rounded-xl ${kpi.iconBoxClassName}`}
          >
            <Icon name={kpi.icon} className="text-[24px]" />
          </div>
        </div>
      ))}
    </section>
  );
}
