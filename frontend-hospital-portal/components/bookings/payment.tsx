import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import type { BookingPayment } from "@/lib/api-types";
import { formatBirr } from "@/lib/format";

/** "Pays at the hospital: ETB 150.00" or "Paid online": what the front desk must know. */
export function paymentText(payment: BookingPayment, price: string): string {
  return payment === "at_hospital" ? `Pays at the hospital: ${formatBirr(price)}` : "Paid online";
}

export function PaymentLabel({
  payment,
  price,
  className,
}: {
  payment: BookingPayment;
  price: string;
  className?: string;
}) {
  const atHospital = payment === "at_hospital";
  return (
    <span
      data-testid="booking-payment"
      data-payment={payment}
      className={cn(
        "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
        atHospital ? "bg-amber-100 text-amber-900" : "bg-emerald-50 text-emerald-800",
        className
      )}
    >
      <Icon name={atHospital ? "payments" : "check_circle"} className="text-[13px]" />
      {paymentText(payment, price)}
    </span>
  );
}
