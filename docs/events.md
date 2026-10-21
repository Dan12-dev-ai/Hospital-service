# Events between the Endod patient platform and the hospital service

Both services talk through **Redis Streams**: each publishes to its own stream
and reads the other's with its own consumer group. Redis is reached through
**Sentinel** in production (the current master is looked up on connect, so a
failover is followed).

| Stream | Written by | Read by (consumer group) |
| --- | --- | --- |
| `endod:patient` | patient platform | hospital service (`hospital-service`) |
| `endod:hospital` | hospital service | patient platform (`patient-platform`) |
| `endod:dead-letter` | either, for events that failed 5 times | people |

Every entry has the fields `id` (unique event id), `type`, `source`,
`occurred_at` (ISO-8601, UTC) and `payload` (JSON).

**Guarantees.** Events are written to an outbox table in the same database
transaction as the change, then relayed to Redis by one publisher at a time,
in order; they count as sent only once Redis (and, with `REDIS_MIN_REPLICAS`,
a replica) has them. None is lost while Redis is down, and none is sent for a
change that was rolled back. Delivery is at least once; each receiver records
handled event ids in the same transaction as the effect, so handling is
exactly once. A failing event is retried after 30 seconds, up to 5 times, then
moved to the dead-letter stream; a malformed one (fails validation) goes there
at once. An event that arrives before the one it depends on (a cancellation
before its booking) is retried until that one has been handled.

Every payload is validated by the receiver; times must carry their offset and
money must be whole santim.

Money is in **santim** (integer, 1/100 birr). Times are ISO-8601 with offset.

## Hospital service → patient platform (`endod:hospital`)

### `hospital.listed`
A hospital patients can book. A full snapshot, sent on approval and on every
change; the platform replaces its copy. `version` rises with every
announcement (listed or unlisted), so a late, older one is ignored.

```json
{"hospital_id": "…", "code": "TASH", "name": "…", "name_am": "…", "kind": "public|private",
 "city": "…", "address": "…", "phone": "…", "ambulance_phone": "…", "emergency": true,
 "latitude": 9.03, "longitude": 38.74, "services": ["general_medicine", "emergency"],
 "open_hours": "…", "timezone": "Africa/Addis_Ababa",
 "video_enabled": true, "price_in_person": 15000, "price_video": 12050, "version": 6}
```

### `hospital.unlisted`
`{"hospital_id": "…", "version": 7}`: not bookable any more (suspended, or the listing is
incomplete). Existing appointments are unaffected.

### `appointment.confirmed`
In-person visits are confirmed on receipt; video visits when a doctor approves
(then `meeting_room` and `doctor_name` are set).
`{"appointment_id", "hospital_id", "status": "confirmed", "meeting_room", "doctor_name", "reason": null}`

### `appointment.rejected`
A video visit was declined (by a doctor, or automatically 15 minutes after its
start time with no approval), or the hospital cannot take the booking. The
platform refunds the patient. `{"appointment_id", "hospital_id", "status", "reason", …}`

### `appointment.cancelled`
Cancelled by the hospital (`"by": "hospital"`). The platform refunds the patient.

### `appointment.completed`
The visit took place. The platform records it and the hospital's payout is due.

## Patient platform → hospital service (`endod:patient`)

### `appointment.requested`
A patient booked and paid. `price` is what the hospital is owed (Endod's
service fee is not included).

```json
{"appointment_id": "…", "hospital_id": "…",
 "patient": {"dedan_id": "DE123456", "name": "…", "phone": "+2519…"},
 "visit_mode": "in_person|video", "service": "general_medicine",
 "scheduled_at": "2026-10-21T09:30:00+00:00", "duration_minutes": 30,
 "notes": "…", "price": 15000}
```

### `appointment.cancelled`
`{"appointment_id", "hospital_id", "by": "patient" | "endod"}`: the patient
cancelled (and was refunded), or Endod refunded a booking the hospital had not
confirmed or declined two hours after its time.

## Patient history, follow-ups, queues and shared records

Linking hospital patients to Endod accounts, clinical records, visits and
follow-ups, queues, records shared by patients and imports add more events to
these same streams. Their contract is in [history-events.md](history-events.md).
