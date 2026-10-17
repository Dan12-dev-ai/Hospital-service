export type PatientStatusKey = "admitted" | "opd" | "emergency" | "discharge";

export type PatientTabKey = "all" | PatientStatusKey;

export type PatientFlag = {
  icon: string;
  label: string;
  className: string;
};

export type Patient = {
  id: string;
  sph: string;
  name: string;
  nameAm: string;
  demographics: string;
  photo: string;
  status: PatientStatusKey;
  statusLabel: string;
  statusBadgeClass: string;
  statusDotClass: string;
  location: string;
  ward: string;
  doctor: string;
  doctorDepartment: string;
  department: string;
  diagnosis: string;
  flag: PatientFlag;
  chartMessage: string;
  scheduleMessage: string;
};
