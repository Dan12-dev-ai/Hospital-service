"use client";

import { useMemo, useState } from "react";
import { AutoDispatchStrip } from "@/components/reports/auto-dispatch-strip";
import { ReportsHeader } from "@/components/reports/reports-header";
import { ReportsKpis } from "@/components/reports/reports-kpis";
import { ReportsTable } from "@/components/reports/reports-table";
import { ReportsToolbar } from "@/components/reports/reports-toolbar";
import { reportRecords } from "@/lib/reports-data";
import type { ReportTabKey } from "@/lib/report-types";

const DEPARTMENT_CATEGORY: Record<string, string> = {
  clinical: "clinical",
  pharmacy: "pharmacy",
  finance: "financial",
  "public-health": "moh",
};

export function ReportsDirectory() {
  const [tab, setTab] = useState<ReportTabKey>("all");
  const [period, setPeriod] = useState("monthly");
  const [department, setDepartment] = useState("all");
  const [format, setFormat] = useState("pdf-excel");

  const filtered = useMemo(() => {
    const departmentCategory = DEPARTMENT_CATEGORY[department];

    return reportRecords.filter((record) => {
      const matchesTab = tab === "all" || record.category === tab;
      const matchesDepartment =
        !departmentCategory || record.category === departmentCategory;

      return matchesTab && matchesDepartment;
    });
  }, [tab, department]);

  return (
    <div className="flex w-full flex-col gap-5">
      <ReportsHeader />
      <ReportsKpis />
      <ReportsToolbar
        tab={tab}
        onTabChange={setTab}
        period={period}
        onPeriodChange={setPeriod}
        department={department}
        onDepartmentChange={setDepartment}
        format={format}
        onFormatChange={setFormat}
      />
      <ReportsTable records={filtered} />
      <AutoDispatchStrip />
    </div>
  );
}
