import type { AgendaEvent } from "@/lib/dashboard-types";

export const agendaEvents: AgendaEvent[] = [
  {
    id: "morning-staff-meeting",
    title: "Morning Staff Meeting",
    time: "08:00 AM",
    description: "Discuss team task and triage distribution for the day.",
    dotClass: "bg-pine-green",
    attendees: [
      "https://lh3.googleusercontent.com/aida-public/AB6AXuDCCkDigQE36CGw1CVXHvHKPTiltlljeK0GOSRLY0_8dXCAQtla7TkjTTfv3UomkGDAUZTVvDaGrmARrMJOT_owjILrHynZ3QqQ9LS2XeK6kU_uAS6tAV2L31sFJ7DK7aduigFeZsadlRg4XOvQ65SLTpVgoHryC3X96_BCHyTSVhtzzZuXhxoG-Oil0Vi78VbWe6TzMgWZFx87jm5HoXtaiewSYlV0Q7r1TGS-ymkvLWNZ8DzX3kIy",
      "https://lh3.googleusercontent.com/aida-public/AB6AXuCYBpmsWX-fZo3uaUjBJB4ouaMCJpcYHwchryge_q61YYRmuxOaoJ4JD7dIqfwmwTqsjg8UUTuj8JONzc69-VJPBGgcHIABi9NVdzzB1UOKtWY-_NFypTjl4-U7EVpjDVV2bcxmscyOmfOIcXKWKjxQ7zbNEGv_Pwd3E3fzzoc9sBBPnYJjWtqNrlsDeLVYnp6sTejKu3TPHnBPZTTSnAebXfq_XXIexmJj5yRG6Wjsx8m3Azzr7g8a",
      "https://lh3.googleusercontent.com/aida-public/AB6AXuAf9GSyPaCZWB4i12xuqwI65zrWh5rPUY61uUZesLY72T_eeaobKPV9eLb5S6NR1c4Z4NIKKp3qyVYNuA9cvNAfKX8ptl8U4JcsJ2gR1_PehnACAxSM9_bJ7b4JSR23_BI7N6B09l_5xU-Imk5rDIwAQXK30bTtt2NbEgKHkTR5lxqn2UM1NamP_DR4G_CxQSMxBzxlSS5eZNI2GbWXFgTwb_L6oL_HFCv2tAF-pJ_e2jMsQaSr7mpi",
    ],
  },
  {
    id: "patient-consultation",
    title: "Patient Consultation",
    time: "08:00 AM",
    description: "Ward rounds with Dr. Hiwot and clinical residents.",
    dotClass: "bg-emerald-400",
    attendees: [
      "https://lh3.googleusercontent.com/aida-public/AB6AXuBJJIuqYjuibn0sBEbtpocMxWVig3S8_lkLkj5IvA31GRXVLp-J8Tl1FCwv7Ps_PGfJ7lnr6Z2ougWB2bplt6pW4UGT6XPFqresuFrT0uM9OW_hDupERijoa0imb4BZnZMHa8hT3fQ9aRpqaGFLb8Hkyz18diBq6C490zG6iHoOm_Gi0kKiuGzuGFNtZ9eUJOeevmeQk8LPfC3_PrDqX9wC6P5M2qmVFxjM7AYiZO_o8SkpfQ6EUZ03",
      "https://lh3.googleusercontent.com/aida-public/AB6AXuD-9N7HvuDaMyWaDDUoghJ9ogLFik4pbjrbfE9H5KPmt-iRfNiErOLmkfXh2UBpfWvrjhAvKZPWYU5NjpwOCnfuzMvIyZzFHj2qkVP8O14ilVSir5oG_5dH_qzXzVoVPQ88ua_EOT3gcNFdc8Nt-NCKVaj4p5PISu5Al7xWVonw2RQmztJj1CF2uZSXbSasHmNkR41ho2rhns1cMOTtOVRQJJMQIY74NqEG8KI4ixN10mt1HmuleNQj",
    ],
  },
  {
    id: "meeting-with-guards",
    title: "Meeting with Guards",
    time: "08:00 AM",
    description: "Crowd management protocols at outpatient main gate.",
    dotClass: "bg-emerald-300",
    attendees: [
      "https://lh3.googleusercontent.com/aida-public/AB6AXuDiMWnv-0fcNv2SPSDCfesZSjOqzBWpgsNueKItH5QESCGgi6dyT6fX37k5eaQX7eqq6335wgYEIScIguB81CFY3NA_-adDVSiheNH8CKr3cinswmHstjGVWWxjwKLy2UpnjHTX5vt2zLP-sV3AWdppl7UZN4vdRzg6q05GeXe2J7cOhTP2nEx_K3_qJM_T-tK-Q6C1XdxXXdfVW9n_KgI9Cb-_DhZZihdL3C38iaVVm-x-PH_wp-al",
      "https://lh3.googleusercontent.com/aida-public/AB6AXuDRh9heqkD8X7JqnpKWPpxWp5baznfyuESHO0Wj99bhDCkaoxZw-gWYBrXz6AMeCqpx7wsMFeAnBAuF3OGSDPQxHQIpyEz375hHQ_Kg7CrPRr7fmS6xEtfy7TLOayN8mAxZBme-v3VczkChvqlszAEuNVgM_3zPnwpGUxLY8YQgFVyPs3QioL_zuwmWYGewSUdXfE1VL96nzXdAaAD-P48-c1Fl7u-PWBo8207MoWwqNp2psgdPklqp",
    ],
  },
  {
    id: "surgery-prep",
    title: "Surgery Prep & Check",
    time: "08:00 AM",
    description: "Pre-op verification for General Surgery Ward.",
    dotClass: "bg-emerald-200",
    attendees: [
      "https://lh3.googleusercontent.com/aida-public/AB6AXuDsTdF651KNg2XX0PZh8t7dgjlIO6SfRixl7hlnDEWkdsqqS3SOXuWJr61r5NJPe5titksFKLRYCnhdBKGHPjqIk-vqqzIZLn_Z5mAKZO_RAcimFe1XM2Y6Hb662npp41AkXEvGShnoJNG7kbv8-dvyflzVOM40DiNe_p0GYVEsEZAshlLNxr6PkaUlxIqjAMN9ie39QWbFftkJwlAGXAeDaV3lCxEskCSYg0Xy0zi24qNfd8l4Bmxd",
      "https://lh3.googleusercontent.com/aida-public/AB6AXuDUp-VAmH1fxtBIe9ytau9-s1wqWXVpCu5SQKvGS4xRxSGh0KWJV6hUDvjqZaaFYfNwlzwCxL1V_xgnyq9qmCb4XW1hoa5Ioir9AiVxqfbIEGFQapIqlwySu7_FyekJTXC6Q0Rc2R-qcj2t2MuCApsdlMD3Z1MVoP44foh_Bd3_3nAzwGLHi9_X52yf_ANCy22dRzmSQNpvlGF9Q0xAuh2Skqeb56F2w6Y_fDNXQkAleMzQ46yOYcL7",
    ],
  },
];
