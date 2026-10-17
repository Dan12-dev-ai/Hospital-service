export type ReportCategoryKey = "clinical" | "pharmacy" | "financial" | "moh";

export type ReportTabKey = "all" | ReportCategoryKey;

export type ReportTab = {
  key: ReportTabKey;
  label: string;
  count: number;
};

export type ReportSelectOption = {
  value: string;
  label: string;
};

export type ReportRecord = {
  id: string;
  name: string;
  meta: string;
  icon: string;
  iconClass: string;
  category: ReportCategoryKey;
  categoryLabel: string;
  categoryDotClass: string;
  frequency: string;
  owner: string;
  ownerMeta: string;
  lastGenerated: string;
  statusLabel: string;
  statusClass: string;
  statusDotClass: string;
};
