# Edge Execution Design & Roadmap

> **Status: PARTIALLY IMPLEMENTED.** This document captures the agreed domain
> model and the plan for *therapy execution* and *repetition quality evaluation*.
> The core — per-repetition good/bad classification, the series lifecycle
> (`start`/`end`/`result`), the durable `serie_executions` table and raw-buffer
> purging — is **now implemented** (see [`movement-monitoring-api.md`](movement-monitoring-api.md)
> §4 for the live contract). Still pending: backend forwarding, fetching
> thresholds from the backend, and the actuator transport. Section 8 tracks the
> exact split. Keep this file as the source of truth for the remaining work.

---

## 1. Why this exists

The edge today ingests raw angles and computes an on-the-fly summary (ROM,
repetitions, etc.). The full system, however, needs more: it must know whether
each repetition was performed **well or badly**, aggregate that per **series**,
and report the **result of a whole therapy execution** to the backend — not
loose readings.

This document records the domain and the edge's role so we can build it later
without re-deriving everything.

---

## 2. Domain model (owned by the BACKEND as definitions)

The clinical configuration is a hierarchy. These are **definitions** (a catalog
the physiotherapist builds); the **edge does not store them**.

```
PLAN  (name, start date, end date — lasts ~1 week / 1 month)
 └── ROUTINE  (name, day of week, time, order within the plan)
      └── SERIES  (order/sequence within the routine; parameters:
      │            target ROM, number of repetitions, quantity,
      │            valoración/rating, rest between series)
      │    └── EXERCISE  (body part: elbow / wrist;
      │                   movement type: pronation / supination
      │                   / flexion / extension)
```

Definitions:

| Concept | Fields |
|---------|--------|
| **Exercise** | body part (elbow / wrist), movement type (pronation / supination / flexion / extension). Generic movement. |
| **Series** | an Exercise + parameters: target ROM (the **average ROM** to report), repetition count, quantity, valoración, rest. Has an order within the routine. |
| **Routine** | a set of Series. Fields: name, day of week, time, order within the plan. |
| **Plan** | a set of Routines + start date + end date (e.g. 1 week / 1 month). |

Related:

| Concept | Meaning |
|---------|---------|
| **Therapy** | references a Plan. |
| **Therapy session** | the **execution** of the plan: when a routine is activated, when it ends, how it is progressing, the execution state, and whether any incorrect / health-damaging movement was detected. |

---

## 3. The boundary: DEFINITION vs EXECUTION

This is the rule that keeps the edge lean.

| Layer | Owner | What it is |
|-------|-------|------------|
| Plan, Routine, Series, Exercise (**definitions**) | **Backend** | The catalog/configuration. The edge does **not** store these. |
| Therapy session (**execution**) | **Edge in real time → Backend at the end** | What actually happened: reps done, good/bad, achieved ROM, unsafe movements. |

**The edge only needs two things:**

1. **The context of the series being executed right now** — its target parameters
   (this comes down from the backend; it is exactly the "threshold decided by the
   backend").
2. **To produce the execution result** of that series — which goes up to the
   backend.

The edge measures *reality* against the configuration the backend holds.

---

## 4. Repetition quality model (the core new capability)

To know whether a repetition is performed **well or badly**, the edge evaluates
**each repetition** against the active series' target. (Today the code only
*counts* reps; this must be upgraded to *evaluate* each one.)

Per repetition, the edge checks:

| Criterion | Good ✅ | Bad ❌ |
|-----------|--------|--------|
| **Range (ROM)** | Reached the series' target ROM | Fell short (incomplete) |
| **Safety** | Within the safe angle | Exceeded the safe limit → **dangerous** → fire actuator |
| **Pattern** (advanced) | Followed the expected movement (flexion/extension/pronation/supination) | Wrong movement |

Then it **aggregates per series**:

- repetitions done, **good**, **bad** (with reason: incomplete / dangerous)
- **average achieved ROM** (the value the series must report)
- **valoración** = quality score (e.g. % of good reps)
- **incorrect/dangerous movement detected** flag

This satisfies the requirements: *"know how many repetitions are good or bad /
whether they are done correctly"* and *"detect incorrect or health-damaging
movement"*.

---

## 5. What the EDGE needs (planned)

### 5.1 Data stored on the edge (SQLite, on the laptop)

| Table | Role | Persistence |
|-------|------|-------------|
| `movement_records` (raw) | Buffer of raw angle readings during a series | **Transient** — purged/capped after the series closes |
| `serie_execution` (**new, durable**) | One row per executed series | **Durable** — this is the chewed result, forwarded to the backend |
| `routine_execution` (optional) | Groups the series executions of one routine | Durable |

**`serie_execution` (proposed fields):**

| Field | Meaning |
|-------|---------|
| `id` | Local execution id |
| `serie_id` | Reference to the series **definition** in the backend |
| `device_id` | Kit that produced the readings |
| `target_rom`, `target_reps`, `movement_type`, `body_part`, `max_safe_angle` | Snapshot of the target parameters (so the result is self-describing) |
| `reps_done`, `good_reps`, `bad_reps_incomplete`, `bad_reps_unsafe` | Repetition outcome |
| `avg_rom` | Average achieved ROM across the reps |
| `min_angle`, `max_angle` | Extremes observed |
| `valoracion` | Computed quality score |
| `dangerous_movement_detected` | Safety flag |
| `started_at`, `ended_at` | Execution window |

### 5.2 Context received from the backend

The target parameters of the **active series**: `target_rom`, repetition count,
`movement_type`, `body_part`, `max_safe_angle`. *(This is the "threshold decided
by the backend".)* For the first iteration these can be passed in the
`series/start` call; later, fetched/cached from the backend.

### 5.3 Endpoints (execution lifecycle — planned)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/.../series/start` | Open a series execution with its target context |
| `POST` | `/api/v1/movement-monitoring/data-records` | Ingest a raw angle (already exists) |
| `POST` | `/api/v1/.../series/end` | Close: classify each rep good/bad, compute avg ROM + valoración, **store** `serie_execution` |
| `GET`  | `/api/v1/.../series/{id}/result` | The chewed result (to view / forward to the backend) |
| *(later)* | forward result to backend + actuator command | |

### 5.4 Execution flow

```
backend ──series target params──▶ EDGE   (POST series/start)
ESP32 ──raw angles──▶ EDGE (buffer) + evaluate each rep live
                              │  (dangerous rep → actuator)
end of series ──▶ EDGE classifies good/bad, avg ROM, valoración
                  ├─ stores serie_execution
                  └─ sends result to backend → therapy session
```

---

## 6. Open decisions (to confirm before building)

1. **Edge stores executions only, never definitions** (plan/routine/series/
   exercise). Proposed: **yes** (correct, keeps the edge lean). — *to confirm*
2. **"Valoración" of a series**: is it **computed by the edge** (quality score =
   % good reps) or **defined by the physiotherapist** in the backend? Listed as a
   series parameter, so clarify whether it is a target (definition) or a result
   (execution). — *to confirm*
3. **Execution granularity**: the edge closes and reports **per series** (each
   series is a clear unit), and the routine/plan are assembled by grouping series
   in the backend. — *to confirm*

---

## 7. Implementation roadmap

1. ✅ **Per-repetition evaluation** — the rep detector emits per-rep details
   (achieved ROM, peak, met-target?, unsafe?) and classifies good/bad.
2. ✅ **Series execution lifecycle** — `series/start` (with target context),
   `series/end` (classify + aggregate + store `serie_execution`), `result`.
3. ✅ **Raw buffer management** — `movement_records` are purged after a series
   closes (and cleared when a new one starts).
4. ⬜ **Backend forwarding** — push the `serie_execution` result to the uFlex REST
   API as part of the therapy session.
5. ⬜ **Threshold from backend** — fetch/cache the active series' parameters from
   the backend instead of passing them in `series/start`.
6. ⬜ **Actuator transport** — send the `ACTIVATE` decision to the device when a
   dangerous movement is detected.

---

## 8. Implemented vs pending (current split)

**Implemented**

- Raw ingestion + auth (`POST .../data-records`)
- On-the-fly analysis: ROM, rep count, min/max/mean, peak angular velocity,
  duration, threshold evaluation (`GET .../analysis`)
- **Per-repetition good/bad classification** (good / incomplete / unsafe)
- **Series lifecycle**: `POST .../series/start`, `POST .../series/end`,
  `GET .../series/{id}/result`
- **Durable `serie_executions` table** (reps done/good/bad, avg ROM, valoración,
  danger flag) + **raw-buffer purging**
- Listing raw readings (`GET .../data-records`)
- Health check (`GET /status`); interactive docs (`GET /scalar`, `/openapi.json`)

**Pending** (roadmap steps 4–6)

- Forwarding the series result to the backend therapy session
- Fetching thresholds/targets from the backend instead of per-request
- Sending the actuator command to the device on dangerous movement
