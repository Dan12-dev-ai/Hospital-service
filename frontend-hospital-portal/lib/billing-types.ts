export type BillingTabKey =
  | "all"
  | "desk"
  | "mobile"
  | "cbhi"
  | "pending";

export type BillingTab = {
  key: BillingTabKey;
  label: string;
  count: number;
};

export type BillingSelectOption = {
  value: string;
  label: string;
};

export type BillingAction = {
  icon: string;
  label: string;
  message: string;
  variant: "primary" | "secondary";
};

export type BillingRecord = {
  id: string;
  cardNumberClass: string;
  mrn: string;
  phone: string;
  name: string;
  nameAm: string;
  initials: string;
  avatarClass: string;
  channel: "desk" | "mobile";
  channelLabel: string;
  channelIcon: string;
  channelIconClass: string;
  channelMeta: string;
  cardType: string;
  cardTypeAm: string;
  fee: string;
  paymentLabel: string;
  paymentBadgeClass: string;
  paymentDotClass: string;
  statusLabel: string;
  statusIcon: string;
  statusBadgeClass: string;
  clinic: string;
  paymentMethod: string;
  tabs: BillingTabKey[];
  action: BillingAction;
};
