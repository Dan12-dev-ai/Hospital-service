import type { Appointment } from "@/lib/dashboard-types";

export const appointments: Appointment[] = [
  {
    id: "DE482731",
    patientName: "Almaz Tefera Kebede",
    patientNameAm: "አልማዝ ተፈራ",
    mrn: "DE482731",
    doctor: "Dr. Hiwot Gebre",
    meta: "Internal Medicine • 48y / A+",
    time: "10:45 AM",
    status: "requested",
    avatar:
      "https://lh3.googleusercontent.com/aida-public/AB6AXuDxFRMT_KpSnInE-PS-Kc96HpSWypsrYMfb2csliI7xqFhEczPETA8MVeN3xDZ3N7DhO_NfVNGJrVu4yEweVpAVBZlk_5chFfsGdzqL1Vux8PootZuAH1yKJG7FqzLoUKNZG1MKzyIPC8K_nmT4OCthmxQyKnsEAUycLa47-2UVe14SCL-n3dCJIqocEa1Dn-qky1ySY-GuGda7_Gx-B2phkxZUq5RJaRcxECyqylT8gIKlwyDDjVyL",
    actionMessage: "Reviewing booking for Almaz Tefera...",
  },
  {
    id: "DE391048",
    patientName: "Dawit Bekele Tadesse",
    patientNameAm: "ዳዊት በቀለ",
    mrn: "DE391048",
    doctor: "Dr. Mulualem T.",
    meta: "Pediatrics • 34y / O+",
    time: "11:00 AM",
    status: "checkedin",
    avatar:
      "https://lh3.googleusercontent.com/aida-public/AB6AXuD5VW42SppH1dTYuULC1otfkqawBOqxFR3S_ZSiXTU2Q78UBUyDNUJ6LfpKgHnmbTE35cTP8EfiN1nPlqgXHj_WvzjT-G73skv12LQWMFCp-yZo1epxErrtddBycFSQgf-Dn6vyCEXQX1zgt_D5mNLUsp1_80v8UGkgK7_9qHshHB_GIhsfFAvesYo7xlRQasliFI9pMPPhGWtKTJJBkIGvKQpgxSO7Ppk1E10i6cdozTNSeJECEl-q",
    actionMessage: "Beginning clinical visit for Dawit Bekele...",
  },
  {
    id: "DE920147",
    patientName: "Sara Hailu Worku",
    patientNameAm: "ሳራ ሀይሉ",
    mrn: "DE920147",
    doctor: "Dr. Aster Demeke",
    meta: "OB/GYN • 29y / B+",
    time: "11:15 AM",
    status: "confirmed",
    avatar:
      "https://lh3.googleusercontent.com/aida-public/AB6AXuBYX-wFxyQw_fWzvAQixYumWjwqXOre8PuVqO96zFKw8XDFjiTzvVN2pgKsGsrtvoRfRq84cyZ6G8DxULJfNI6Lq7twrwjTHmtDQJKsBseWCxvA53AfHybgE63ytTOnckbonmEcehmq590XYAsayNyp0uVxhhpmrCmyWIBLyM8zXsu5lGGbN2G4UaI5QYDTqxpJzp5hBILNfP_gdVb8nsl37vSbwTJL5FzcJxazMUmND2s-jm0Z1kHx",
    actionMessage: "Sara Hailu marked as checked in",
  },
  {
    id: "DE771209",
    patientName: "Yohannes Girma Assefa",
    patientNameAm: "ዮሐንስ ግርማ",
    mrn: "DE771209",
    doctor: "Dr. Hiwot Gebre",
    meta: "Exam Room 204 • 62y / AB+",
    time: "11:30 AM",
    status: "confirmed",
    avatar:
      "https://lh3.googleusercontent.com/aida-public/AB6AXuACSugBXAojI3RqC8VE2Wl1sfYONCfpPflQNgLgczwO9JJP13GLSTvP6xu7uaR_No4USMkUQreeJh2v1wxLGx0nVoP64lMF9bVh-5KbmJCRG--0hMaBHkwj6EUFCoFlUDgtFmR4fIfpZU11jKRJ_mNnRXDwjfR24dMKRXwXxqVynSMHi6g4PmAcsZwLUZ616mwzCN2T9BNO2r47I9mkyKP13QWurbd2ykGFBDXWYMXU7DsRHRqsjCVT",
    actionMessage: "Opening clinical EHR chart for Yohannes Girma...",
  },
  {
    id: "DE663291",
    patientName: "Meron Tesfaye Alemu",
    patientNameAm: "ሜሮን ተስፋዬ",
    mrn: "DE663291",
    doctor: "Dr. Kassahun Z.",
    meta: "General Surgery • 41y / A-",
    time: "11:45 AM",
    status: "requested",
    avatar:
      "https://lh3.googleusercontent.com/aida-public/AB6AXuDKjOCwBnVhfm3y9rOBF-o8io9nSebo05n9ICUQ7QCt1WSl5VTXOON8CmE_aL_Zkc4MOiEu7NUa0ZszAyU81E4svBU0MJqghTwKQZ3ibJCFRQCscr6DdQaa7nyO6kd0kfISV3mkkgySIXueQPnrRbwJ4wAr-OjG6cYEx5YQKTrwAGEuo2pNJh5vFKg-WuquEL1lIAV2IpIvRIWUzu4Rmzx8fcWxOq68U3rrlr1p5VUIK8f4NVzUKYyy",
    actionMessage: "Reviewing surgery intake for Meron...",
  },
];
