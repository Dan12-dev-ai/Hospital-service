import type { AlertItem, KpiMetric, NavItem } from "@/lib/dashboard-types";

// Illustrative data for the parts of the portal that have no backend yet
// (billing, pharmacy, reports, the dashboard's charts). They are badged
// "Sample data" wherever they appear.

export const facility = {
  name: "St. Paul's Millennium",
  nameAm: "ቅዱስ ጳውሎስ ሆስፒታል",
  fullName: "St. Paul's Millennium Medical Center",
};

export const navItems: NavItem[] = [
  { label: "Dashboard", icon: "grid_view", href: "/" },
  { label: "Patients", icon: "person", href: "/patients" },
  { label: "Doctors", icon: "stethoscope", href: "/doctors" },
  {
    label: "Appointments",
    icon: "calendar_month",
    href: "/appointments",
    // The backend's booking viewers.
    roles: ["admin", "doctor", "nurse", "reception"],
  },
  // Doctors' queues: the desk runs them all, a doctor their own.
  { label: "Queue", icon: "format_list_numbered", href: "/queue", roles: ["admin", "reception", "doctor"] },
  // Records patients shared through Endod: the clinical record readers.
  {
    label: "Shared records",
    icon: "folder_shared",
    href: "/shared",
    roles: ["admin", "doctor", "nurse", "pharmacist", "records"],
  },
  { label: "Import", icon: "upload_file", href: "/import", roles: ["admin", "records"] },
  { label: "Billing", icon: "receipt_long", href: "/billing" },
  { label: "Pharmacy", icon: "medication", href: "/pharmacy" },
  { label: "Reports", icon: "description", href: "/reports" },
  { label: "Settings", icon: "settings", href: "/settings", roles: ["admin"] },
];

/** Billing is not connected to the hospital service yet: an illustrative card. */
export const sampleInvoiceMetric: KpiMetric = {
  label: "Invoices",
  icon: "receipt",
  value: "347",
  trend: "+1.5%",
  caption: "28 Confirmed today",
  sample: true,
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
