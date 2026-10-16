import type { AlertItem, KpiMetric, NavItem } from "@/lib/dashboard-types";

export const facility = {
  name: "St. Paul's Millennium",
  nameAm: "ቅዱስ ጳውሎስ ሆስፒታል",
  fullName: "St. Paul's Millennium Medical Center",
};

export const currentUser = {
  name: "Admin User",
  email: "admin@hospital.com",
  initials: "RM",
};

export const signedInDoctor = {
  name: "Dr. Hiwot M. Gebre",
  specialty: "Internal Medicine • MD",
  avatar:
    "https://lh3.googleusercontent.com/aida-public/AB6AXuBrFt935q0jVx2nJZbNGs4PWc-ZQdQ_rcChfWqY2G6k7213iCc0cVqUaoV7D4KFAAmQJevMo94Ei8e8-McpwAkkrRmW3h7BIf4_gTJBsrpFyzATurRSt90l20-Zeo5TZmixS2GTrDjWWOysBbiUXvxsdNVezi6wkrG_Ad-f59mWa14_1FPfh717am7TumNYmyhPgcCS-1DH8YQYQ4Dr_7WjuB_uUKeOJgII5WSWp_A",
};

export const navItems: NavItem[] = [
  { label: "Dashboard", icon: "grid_view", href: "/", badge: "4" },
  { label: "Patients", icon: "person", href: "/patients" },
  { label: "Doctors", icon: "stethoscope", href: "/doctors", dot: true },
  {
    label: "Appointments",
    icon: "calendar_month",
    href: "/appointments",
    badge: "145",
  },
  { label: "Billing", icon: "receipt_long", href: "/billing" },
  { label: "Pharmacy", icon: "medication", href: "/pharmacy" },
  { label: "Reports", icon: "description", href: "/reports" },
  { label: "Settings", icon: "settings", href: "/settings" },
];

export const kpiMetrics: KpiMetric[] = [
  {
    label: "Total Patients",
    icon: "groups",
    value: "1,105",
    trend: "+1.5%",
    caption: "20 more than yesterday",
  },
  {
    label: "Appointments",
    icon: "calendar_today",
    value: "145",
    trend: "+1.5%",
    caption: "42 today • 5 awaiting triage",
  },
  {
    label: "Invoices",
    icon: "receipt",
    value: "347",
    trend: "+1.5%",
    caption: "28 Confirmed today",
  },
  {
    label: "Staff on Duty",
    icon: "badge",
    value: "24",
    trend: "+1.5%",
    caption: "09 Waiting in Triage Area B",
  },
];

export const liveIntake = {
  patientName: "Almaz Tefera Kebede",
  mrn: "DE482731",
  detail: "Internal Medicine (Ward B) • 2 mins ago",
};

export const hospitalAlerts: AlertItem[] = [
  {
    id: "low-stock",
    message: "Low stock alert: Paracetamol & Normal Saline infusion tablets",
  },
  {
    id: "triage-pending",
    message: "3 outpatient appointments pending clinical triage confirmation",
  },
  {
    id: "equipment-maintenance",
    message: "Equipment maintenance due: MRI Suite 2 • Biomedical Dept",
  },
];
