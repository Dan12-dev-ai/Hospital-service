export type AppointmentStatus =
  | "in-consultation"
  | "waiting"
  | "checked-in"
  | "scheduled"
  | "completed"
  | "pending";

export type AppointmentRow = {
  id: string;
  patientName: string;
  patientNameAm: string;
  /** e.g. "DE-482731" */
  mrn: string;
  /** e.g. "SPH-9941" */
  sph: string;
  /** e.g. "48y F" */
  demographics: string;
  /** Photo URL; when null the initials avatar is shown instead */
  photo: string | null;
  /** Initials for the fallback avatar (e.g. "SH") */
  initials: string;
  /** Background/foreground classes for the initials avatar */
  initialsClass: string;
  time: string;
  /** Highlight the schedule clock icon (true for in-consultation rows) */
  timeAccent: boolean;
  visitType: string;
  /** Department key — matches the department <select> option value */
  department: string;
  /** Visit-type key — matches the visit-type <select> option value */
  visitTypeKey: string;
  doctor: string;
  doctorMeta: string;
  status: AppointmentStatus;
  statusLabel: string;
  /** Status pill background/text classes */
  statusClass: string;
  /** Status pill leading dot classes */
  statusDotClass: string;
  note: string;
  /** Note chip background/text classes */
  noteClass: string;
  /** Action button label — "Open Chart" or "Start Visit" */
  actionLabel: string;
  /** Whether the action button uses the filled primary style */
  actionPrimary: boolean;
};
