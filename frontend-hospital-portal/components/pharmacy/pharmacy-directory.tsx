"use client";

import { useMemo, useState } from "react";
import { PharmacyHeader } from "@/components/pharmacy/pharmacy-header";
import { PharmacyKpis } from "@/components/pharmacy/pharmacy-kpis";
import { PharmacyToolbar } from "@/components/pharmacy/pharmacy-toolbar";
import { PharmacyTable } from "@/components/pharmacy/pharmacy-table";
import { pharmacyRecords } from "@/lib/pharmacy-data";
import type { PharmacyTabKey } from "@/lib/pharmacy-types";

export function PharmacyDirectory() {
  const [tab, setTab] = useState<PharmacyTabKey>("all");
  const [dispensary, setDispensary] = useState("all");
  const [category, setCategory] = useState("all");

  const filtered = useMemo(() => {
    return pharmacyRecords.filter((record) => {
      const matchesTab = tab === "all" || record.tabs.includes(tab);
      const matchesDispensary =
        dispensary === "all" || record.dispensary === dispensary;
      const matchesCategory =
        category === "all" || record.category === category;

      return matchesTab && matchesDispensary && matchesCategory;
    });
  }, [tab, dispensary, category]);

  return (
    <div className="flex w-full flex-col gap-5">
      <PharmacyHeader />
      <PharmacyKpis />
      <PharmacyToolbar
        tab={tab}
        onTabChange={setTab}
        dispensary={dispensary}
        onDispensaryChange={setDispensary}
        category={category}
        onCategoryChange={setCategory}
      />
      <PharmacyTable records={filtered} />
    </div>
  );
}
