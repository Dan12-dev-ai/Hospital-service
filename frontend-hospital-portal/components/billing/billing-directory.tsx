"use client";

import { useMemo, useState } from "react";
import { BillingHeader } from "@/components/billing/billing-header";
import { BillingKpis } from "@/components/billing/billing-kpis";
import { BillingToolbar } from "@/components/billing/billing-toolbar";
import { BillingTable } from "@/components/billing/billing-table";
import { IssueCardModal } from "@/components/billing/issue-card-modal";
import { billingRecords } from "@/lib/billing-data";
import type { BillingTabKey } from "@/lib/billing-types";

export function BillingDirectory() {
  const [modalOpen, setModalOpen] = useState(false);
  const [filterQuery, setFilterQuery] = useState("");
  const [tab, setTab] = useState<BillingTabKey>("all");
  const [clinic, setClinic] = useState("all");
  const [paymentMethod, setPaymentMethod] = useState("all");

  const filtered = useMemo(() => {
    const search = filterQuery.toLowerCase().trim();
    return billingRecords.filter((record) => {
      const haystack = [
        record.id,
        record.mrn,
        record.phone,
        record.name,
        record.nameAm,
        record.channelLabel,
        record.channelMeta,
        record.cardType,
        record.cardTypeAm,
        record.fee,
        record.paymentLabel,
        record.statusLabel,
      ]
        .join(" ")
        .toLowerCase();

      const matchesSearch = !search || haystack.includes(search);
      const matchesTab = tab === "all" || record.tabs.includes(tab);
      const matchesClinic = clinic === "all" || record.clinic === clinic;
      const matchesPayment =
        paymentMethod === "all" || record.paymentMethod === paymentMethod;

      return matchesSearch && matchesTab && matchesClinic && matchesPayment;
    });
  }, [filterQuery, tab, clinic, paymentMethod]);

  return (
    <div className="flex w-full flex-col gap-5">
      <BillingHeader
        onIssueCard={() => setModalOpen(true)}
      />
      <BillingKpis />
      <BillingToolbar
        filterQuery={filterQuery}
        onFilterQueryChange={setFilterQuery}
        tab={tab}
        onTabChange={setTab}
        clinic={clinic}
        onClinicChange={setClinic}
        paymentMethod={paymentMethod}
        onPaymentMethodChange={setPaymentMethod}
      />
      <BillingTable records={filtered} />
      <IssueCardModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </div>
  );
}
