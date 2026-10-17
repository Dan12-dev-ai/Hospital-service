export type PharmacyTabKey =
  | "all"
  | "pending"
  | "dispensed"
  | "review"
  | "low-stock";

export type PharmacyRecordStatus = "pending" | "dispensed" | "review";

export type PharmacySelectOption = {
  value: string;
  label: string;
};

export type PharmacyTab = {
  key: PharmacyTabKey;
  label: string;
  count: number;
};

export type PharmacyAction = {
  label: string;
  variant: "primary" | "secondary";
  message: string;
};

export type PharmacyRecord = {
  id: string;
  mrn: string;
  name: string;
  nameAm: string;
  initials: string;
  avatarClass: string;
  medication: string;
  medicationIcon: string;
  medicationIconClass: string;
  dosage: string;
  physician: string;
  physicianMeta: string;
  coverage: string;
  coverageIcon: string;
  coverageClass: string;
  status: PharmacyRecordStatus;
  statusLabel: string;
  statusClass: string;
  statusDotClass: string;
  statusIcon?: string;
  action: PharmacyAction;
  dispensary: string;
  category: string;
  tabs: PharmacyTabKey[];
};
