# Movement Monitoring API — Edge Contract

This document describes the HTTP contract of the **Detection** bounded context:
what an IoT Kit (or any client) must **send**, what the gateway **returns**, and
what the edge **processes** in between.

> The uFlex Edge Gateway is the edge component of a tele-rehabilitation system.
> An ESP32-based kit measures a joint **flexion angle** (degrees) with IMU
> sensors and streams it to this gateway. The gateway authenticates the kit,
> stores the raw readings, and — this is its core job — **chews those raw
> readings into clinical metrics** (range of motion, repetitions, speed) and
> evaluates them against backend-defined thresholds to decide whether an
> actuator should fire.

---

## Endpoint summary

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/api/v1/movement-monitoring/data-records` | Yes | Ingest one raw angle reading from a kit |
| `GET`  | `/api/v1/movement-monitoring/analysis` | No | **Digested summary** (ROM, reps, …) + actuator decision |
| `GET`  | `/api/v1/movement-monitoring/data-records` | No | List recent raw readings (live view / debugging) |
| `POST` | `/api/v1/movement-monitoring/series/start` | Yes | Open a series execution with its target parameters |
| `POST` | `/api/v1/movement-monitoring/series/end` | Yes | Close the series: classify reps good/bad, store result |
| `GET`  | `/api/v1/movement-monitoring/series/{id}/result` | No | Read a stored series execution result |
| `GET`  | `/status` | No | Health check — is the edge up and reachable? |
| `GET`  | `/scalar` | No | Interactive API reference (Scalar UI) |
| `GET`  | `/openapi.json` | No | Machine-readable OpenAPI 3.1 document |

Base URL during development: `http://<laptop-LAN-ip>:5050` (the gateway listens
on `0.0.0.0:5050`). The LAN IP is DHCP-assigned and changes between networks.

**Browse it interactively:** open `http://localhost:5050/scalar` for a Scalar API
reference of every endpoint below (the same UI used by the uFlex REST API
backend).

---

## 1. Ingest a reading — `POST /api/v1/movement-monitoring/data-records`

The endpoint the **embedded device** calls, once per sample.

### Send

**Headers (required)**

| Header | Value |
|--------|-------|
| `X-API-Key` | The kit's secret key (dev kit: `test-api-key-123`) |
| `Content-Type` | `application/json` |

**Body (JSON)**

| Field | Type | Required | Rule |
|-------|------|----------|------|
| `device_id` | string | **yes** | Must match a registered kit (dev kit: `uflex-kit-001`) |
| `angle` | number | **yes** | Joint flexion in degrees, `0 ≤ angle ≤ 360` |
| `created_at` | string (ISO 8601) | no | Reading timestamp; defaults to current UTC if omitted |

```json
{ "device_id": "uflex-kit-001", "angle": 92.5, "created_at": "2026-06-16T18:23:00-05:00" }
```

### Returns

| Status | When | Body |
|--------|------|------|
| `201 Created` | Reading stored | The persisted record with its `id` and a UTC `created_at` |
| `400 Bad Request` | Missing field or invalid value (angle out of `[0,360]`, bad timestamp) | `{ "error": "..." }` |
| `401 Unauthorized` | Missing/invalid `device_id` or `X-API-Key` | `{ "error": "..." }` |

```json
{ "id": 42, "device_id": "uflex-kit-001", "angle": 92.5, "created_at": "2026-06-16T23:23:00+00:00Z" }
```

### Processes

Validates the angle range, normalizes `created_at` to UTC, and persists the raw
reading to SQLite. No aggregation happens here — that is the job of the analysis
endpoint below.

---

## 2. Digested summary — `GET /api/v1/movement-monitoring/analysis`

The **core processing output** of the edge. Aggregates a kit's recent readings
into clinical metrics and, when thresholds are supplied, decides the actuator
action.

### Send

**Query parameters**

| Param | Type | Required | Meaning |
|-------|------|----------|---------|
| `device_id` | string | **yes** | Kit to analyse |
| `limit` | int | no | Number of most-recent readings to analyse (default `200`) |
| `target_rom` | float | no | Backend range-of-motion goal, degrees |
| `max_safe_angle` | float | no | Backend safety ceiling, degrees |

```
GET /api/v1/movement-monitoring/analysis?device_id=uflex-kit-001&target_rom=80&max_safe_angle=100
```

### Returns — `200 OK`

```json
{
  "device_id": "uflex-kit-001",
  "sample_count": 57,
  "min_angle": 20.0,
  "max_angle": 110.0,
  "range_of_motion": 90.0,
  "mean_angle": 62.63,
  "repetitions": 3,
  "peak_angular_velocity": 10.0,
  "duration_seconds": 56.0,
  "threshold_evaluation": {
    "target_rom": 80.0,
    "rom_goal_met": true,
    "max_safe_angle": 100.0,
    "safe_limit_exceeded": true,
    "actuator_action": "ACTIVATE"
  }
}
```

Returns `400 Bad Request` if `device_id` is missing. When there are no readings
yet, numeric fields are `null` and `repetitions` is `0`.

### Field reference (what we process)

| Field | Definition |
|-------|------------|
| `sample_count` | Number of readings included in the analysis |
| `min_angle` / `max_angle` | Lowest / highest flexion angle observed (extension / flexion peaks) |
| `range_of_motion` | `max_angle − min_angle`. The primary rehabilitation metric |
| `mean_angle` | Average flexion angle |
| `repetitions` | Full flex-and-return cycles, counted with a hysteresis state machine that rejects sensor jitter (see below) |
| `peak_angular_velocity` | Fastest instantaneous speed between consecutive readings, in degrees/second |
| `duration_seconds` | Elapsed time spanned by the readings |
| `threshold_evaluation` | Comparison against backend thresholds; `null` when none supplied |

**Threshold evaluation block**

| Field | Definition |
|-------|------------|
| `rom_goal_met` | `range_of_motion ≥ target_rom` — did the patient reach the goal? |
| `safe_limit_exceeded` | `max_angle ≥ max_safe_angle` — was a safety ceiling crossed? |
| `actuator_action` | `"ACTIVATE"` when the safe limit is exceeded, else `"IDLE"`. Consumed by the (future) actuator transport |

**Repetition detection algorithm.** The whole series must span at least
`MIN_ROM_FOR_REP` (10°) to contain any repetition. The detector then walks the
series tracking a *local* extension baseline: a flexion starts when the angle
rises at least `excursion_threshold` above that baseline, and the repetition is
recorded when it falls back by the same amount. The threshold is derived from
the target ROM (`REP_DETECTION_FRACTION` = 50% of `target_rom`, with a 10° floor;
falls back to 10° when no target is given). Using a **local baseline rather than
the global peak** is what lets repetitions of *different amplitude* all be
detected — a smaller rep is no longer hidden by a taller one elsewhere in the
series.

---

## 3. List raw readings — `GET /api/v1/movement-monitoring/data-records`

For a live view or debugging.

### Send

| Param | Type | Required | Meaning |
|-------|------|----------|---------|
| `device_id` | string | no | Restrict to one kit (chronological order). Omit for all kits (newest first) |
| `limit` | int | no | Maximum readings to return (default `100`) |

### Returns — `200 OK`

```json
[
  { "id": 42, "device_id": "uflex-kit-001", "angle": 92.5, "created_at": "2026-06-16T23:23:00+00:00" }
]
```

---

## 4. Series execution — the routine lifecycle

A **series** is the unit of exercise a patient performs (an exercise plus its
target parameters). The edge measures the *execution* of a series and produces a
durable, chewed result; the *definition* of the series/routine/plan lives in the
backend. See [`edge-execution-design.md`](edge-execution-design.md).

Lifecycle: `series/start` → raw `data-records` posted while the patient moves →
`series/end` (classifies each repetition and stores the result) → `series/{id}/result`.

### 4.1 Open a series — `POST .../series/start`

**Headers (required):** `X-API-Key`, `Content-Type: application/json`.

**Body (JSON)**

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `device_id` | string | **yes** | The kit performing the series |
| `serie_id` | string | no | Reference to the series **definition** in the backend |
| `target_rom` | number | no | Target range of motion (deg); reps below it are *incomplete* |
| `target_reps` | int | no | Expected repetition count |
| `movement_type` | string | no | pronation / supination / flexion / extension |
| `body_part` | string | no | elbow / wrist |
| `max_safe_angle` | number | no | Safety ceiling (deg); reps reaching it are *unsafe* |

Starting a series **clears the raw buffer** for that kit, so readings posted next
belong to this series. Returns `201` with the opened execution (`status: OPEN`).

### 4.2 Close a series — `POST .../series/end`

**Headers (required):** `X-API-Key`, `Content-Type: application/json`.
**Body (JSON):** `device_id` *(string, required)*.

Reads the buffered readings, **classifies every repetition** (good / incomplete /
unsafe), aggregates the outcome, persists it, and purges the raw buffer.

**Returns — `200 OK`**

```json
{
  "id": 1, "serie_id": "serie-abc", "device_id": "uflex-kit-001", "status": "CLOSED",
  "target_rom": 70.0, "target_reps": 4, "movement_type": "flexion", "body_part": "codo",
  "max_safe_angle": 130.0,
  "reps_done": 4, "good_reps": 2, "bad_reps_incomplete": 1, "bad_reps_unsafe": 1,
  "avg_rom": 78.75, "min_angle": 20.0, "max_angle": 140.0,
  "valoracion": 50.0, "dangerous_movement_detected": true,
  "started_at": "2026-06-16T12:00:00+00:00", "ended_at": "2026-06-16T12:00:57+00:00",
  "repetitions": [
    { "achieved_rom": 80.0, "peak_angle": 100.0, "met_target": true,  "unsafe": false, "classification": "good" },
    { "achieved_rom": 40.0, "peak_angle": 60.0,  "met_target": false, "unsafe": false, "classification": "incomplete" },
    { "achieved_rom": 75.0, "peak_angle": 95.0,  "met_target": true,  "unsafe": false, "classification": "good" },
    { "achieved_rom": 120.0,"peak_angle": 140.0, "met_target": true,  "unsafe": true,  "classification": "unsafe" }
  ]
}
```

Returns `400` when there is no open series for the kit, `401` on bad credentials.

### 4.3 Result field reference

| Field | Definition |
|-------|------------|
| `reps_done` | Repetitions detected in the series |
| `good_reps` | Reps that met the target ROM **and** stayed within the safe angle |
| `bad_reps_incomplete` | Reps that fell short of `target_rom` |
| `bad_reps_unsafe` | Reps whose peak reached `max_safe_angle` (dangerous) |
| `avg_rom` | Average achieved ROM across the reps — the value the series reports |
| `valoracion` | Quality score = percentage of good reps |
| `dangerous_movement_detected` | `true` if any unsafe rep occurred (would fire the actuator) |
| `repetitions[]` | Per-rep breakdown: `achieved_rom`, `peak_angle`, `met_target`, `unsafe`, `classification` (`good` / `incomplete` / `unsafe`) |

### 4.4 Read a stored result — `GET .../series/{id}/result`

Returns `200` with the stored execution, or `404` when it does not exist.

---

## 5. Health check — `GET /status`

### Returns — `200 OK`

```json
{ "status": "ok", "service": "uflex-edge-gateway" }
```

Used to confirm the gateway process is up and reachable on the network without
touching the authenticated data endpoints.

---

## End-to-end flow

```
backend ──series target params──▶ EDGE                 (POST series/start; clears buffer)
ESP32 ──POST raw angle (1/sec)──▶ EDGE ──buffer──▶ SQLite (movement_records, transient)
                                   │
              live view ──GET analysis──▶ on-the-fly summary (ROM, reps, velocity)
                                   │
end of series ──POST series/end──▶ EDGE classifies each rep good/bad,
                                   │   aggregates avg ROM / valoracion / danger,
                                   │   stores serie_executions (durable), purges buffer
                                   ▼
                          series result (JSON) ──▶ (future) backend therapy session
```

## Not wired up yet (next steps)

- **Thresholds from the backend.** `target_rom` / `max_safe_angle` / `target_reps`
  are supplied per request today (query params on `analysis`, body on
  `series/start`); they are meant to be fetched/cached from the cloud backend.
- **Actuator transport.** `dangerous_movement_detected` / `actuator_action` is
  computed but not yet sent to the device.
- **Cloud forwarding.** The stored `serie_executions` result is not yet pushed to
  the uFlex REST API; the edge currently only stores and serves it locally.
