export type DoctorStatus =
  | "on-duty"
  | "in-consultation"
  | "on-call"
  | "off-duty";

export type Doctor = {
  id: string;
  name: string;
  nameAm: string;
  license: string;
  credentials: string;
  /** e.g. "F / 46" */
  demographics: string;
  photo: string;
  /** Filter key — matches the department <select> option value */
  department: string;
  /** Display label, e.g. "General Surgery & Trauma" */
  departmentLabel: string;
  specialty: string;
  /** Filter key — matches the rank <select> option value */
  rank: string;
  rankLabel: string;
  status: DoctorStatus;
  /** Display text inside the status pill, e.g. "On Duty • OPD Rm 204" */
  statusLabel: string;
  /** Status pill background/text classes (varies per row in the template) */
  statusBadgeClass: string;
  /** Status pill leading dot color class */
  statusDotClass: string;
  /** e.g. "18 / 22 Patients" */
  loadLabel: string;
  /** e.g. "82%" or "OR Active" — shown on the right of the load bar */
  loadCaption: string;
  /** 0-100 fill width of the load progress bar */
  loadPercent: number;
  /** Progress bar fill color class */
  loadBarClass: string;
  phone: string;
  extension: string;
  /** Toast messages for the row action buttons */
  profileMessage: string;
  scheduleMessage: string;
  messageMessage: string;
};

export type DoctorStatusFilter = "all" | DoctorStatus;
