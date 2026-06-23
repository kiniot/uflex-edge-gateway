# uFlex Edge Gateway

`uflex-edge-gateway` is a lightweight IoT edge API for ingesting range-of-motion
telemetry emitted by uFlex IoT Kits during tele-rehabilitation sessions. The
service follows a Domain-Driven Design (DDD) approach and separates the
device-authentication concerns from the movement-telemetry ingestion concerns.

uFlex is a medical-grade tele-rehabilitation platform: patients perform guided
exercises while an IoT Kit equipped with IMU sensors measures the joint flexion
angle (range of motion). This gateway is the edge component that authenticates
each kit and reliably captures its angle readings before they are forwarded to
the cloud backend.

At its current stage, the service provides:

- device (IoT Kit) authentication using `serial_number` + `X-API-Key`
- ingestion of joint-angle samples and **streaming detection** of repetitions and
  compensatory movements
- **durable, idempotent forwarding** of detected events to the cloud backend, plus
  a live progress stream (SSE) to the patient app
- SQLite persistence through Peewee ORM
- a layered architecture aligned with DDD bounded contexts

## Current Scope

This repository currently implements a focused subset of the uFlex IoT-edge
solution:

- **Implemented**
  - registration/lookup of a development test kit, identified by `serial_number`
  - authentication of kit-originated requests (`serial_number` + `X-API-Key`)
  - **enriched batch ingestion** of joint-angle samples
    (`{target_angle, proximal_signal}`) at the kit's cadence, plus the legacy
    single-`angle` path (`POST .../data-records`)
  - **streaming per-repetition detection** (hysteresis) with quality
    classification (good / incomplete / unsafe)
  - **compensation detection**: proximal segment sweeping while the target joint
    stalls → a `ShoulderCompensation` event
  - **durable outbox + forwarding worker**: detected reps and compensations are
    persisted and forwarded to the cloud backend in FIFO order, **idempotently**
    (`X-Edge-Sequence-Id`) and retried on failure
  - **active-context poller + endpoint**: pulls the active serie/joint and
    `max_safe_angle` from the backend and serves it to the kit
    (`GET .../active-context`)
  - **live progress over SSE**: per-serie repetition tallies pushed to the
    patient app (`GET .../progress-stream`)
  - authenticated backend client (lazy `ROLE_EDGE` sign-in, refresh-on-401)
  - movement analysis (ROM, rep count, min/max/mean, peak velocity, duration —
    `GET .../analysis`) and recent raw readings (`GET .../data-records`)
  - timestamp normalization to UTC, SQLite persistence (Peewee)
  - a health check endpoint (`GET /status`) and interactive API docs via Scalar
    (`GET /scalar`, `GET /openapi.json`)
- **Not implemented yet**
  - sending an actuator decision to the device — the kit now enforces
    `max_safe_angle` **locally** (no network round-trip on the safety path)
  - **SSE auth/discovery**: the progress stream is currently unauthenticated on
    the LAN; mDNS discovery + a pairing token is the planned follow-on
  - battery / kit-status telemetry

See [`docs/movement-monitoring-api.md`](docs/movement-monitoring-api.md) for the
full request/response contract and the definition of every processed metric.

> **Note:** [`docs/edge-execution-design.md`](docs/edge-execution-design.md)
> predates the per-repetition streaming redesign — its `series start/end/result`
> lifecycle and the `serie_executions` table no longer exist. The authoritative,
> up-to-date cross-repo status lives in the patient app's **`EXECUTION-CONTRACT.md`**
> (section "Estado de implementación (Olas 1–2)").

Keeping the README aligned with the implemented scope is especially important
in IoT projects, where device contracts and API behavior must remain explicit
and dependable.

## Why DDD for an IoT Edge Gateway?

In IoT systems, devices, telemetry, authentication, and persistence often grow
quickly and evolve independently. DDD helps keep that complexity manageable by
organizing the code around business capabilities instead of technical concerns.

This service is split into two bounded contexts:

### 1. IAM (Identity and Access Management)

Responsible for identifying IoT Kits and validating their credentials.

- **Core concept**: `Device` (an IoT Kit identified by its serial number)
- **Primary responsibility**: authenticate incoming requests from kits

### 2. Detection

Responsible for validating and storing movement telemetry.

- **Core concept**: `MovementRecord`
- **Primary responsibility**: accept joint flexion angle readings and persist them

The Detection context depends on IAM only for device validation, which keeps the
telemetry model decoupled from authentication details.

## Layered Architecture

Each bounded context follows the same DDD-inspired structure:

- **Domain** — entities and domain services; business rules and invariants; no
  framework or ORM concerns
- **Application** — orchestration of use cases; coordinates repositories and
  domain services
- **Infrastructure** — Peewee models, repository implementations, persistence
  details
- **Interfaces** — Flask HTTP endpoints and request handling

### Project Structure

```text
uflex-edge-gateway/
├── app/
│   ├── main.py
│   ├── detection/
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   └── interfaces/
│   ├── iam/
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   └── interfaces/
│   └── shared/
│       ├── infrastructure/
│       └── interfaces/
├── tests/
├── pytest.ini
└── docs/
```

## Technology Stack

- Python 3.13+
- Flask
- Peewee
- SQLite
- python-dateutil

Exact Python dependencies are declared in [`requirements.txt`](requirements.txt).

## Getting Started

### 1. Create a virtual environment

```sh
python -m venv .venv
.venv\Scripts\activate    # Windows (PowerShell)
# source .venv/bin/activate  # Linux / macOS
```

### 2. Install dependencies

```sh
pip install -r requirements.txt
```

### 3. Run the service

```sh
python -m app.main
```

The Flask application runs in debug mode when started this way. Run it as a
module (`-m`) from the repository root, not `python app/main.py`, so the
absolute `app.*` imports resolve.

## Runtime Behavior

The application performs bootstrap work before serving the first request:

- initializes the SQLite database
- creates the `devices` and `movement_records` tables if they do not exist
- seeds a development test kit if absent

Database initialization is triggered by the Flask `before_request` hook, so the
setup occurs on the first incoming HTTP request handled by the process.

## Development Test Kit

For local development, the application seeds the following IoT Kit if it is not
already present in the database:

- `device_id`: `uflex-kit-001`
- `api_key`: `test-api-key-123`

> [!WARNING]
> These credentials are hard-coded for local development only. Do not reuse
> them in production or on real IoT deployments.

## API Contract

### Create a movement record

`POST /api/v1/movement-monitoring/data-records`

Creates a new joint-flexion reading for an authenticated IoT Kit.

#### Required headers

- `Content-Type: application/json`
- `X-API-Key: <kit api key>`

#### Request body

```json
{
  "device_id": "uflex-kit-001",
  "angle": 92.5,
  "created_at": "2026-05-29T18:23:00-05:00"
}
```

#### Request fields

- `device_id` (`string`, required): unique IoT Kit identifier (serial number)
- `angle` (`number`, required): joint flexion angle in degrees
- `created_at` (`string`, optional): ISO 8601 timestamp; when omitted, the
  service uses the current UTC time

#### Example request

```sh
curl -X POST http://127.0.0.1:5050/api/v1/movement-monitoring/data-records \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: test-api-key-123' \
  -d '{
        "device_id": "uflex-kit-001",
        "angle": 92.5,
        "created_at": "2026-05-29T18:23:00-05:00"
      }'
```

#### Success response

`201 Created`

```json
{
  "id": 1,
  "device_id": "uflex-kit-001",
  "angle": 92.5,
  "created_at": "2026-05-29T23:23:00+00:00Z"
}
```

#### Error responses

- `400 Bad Request`
  - missing required fields
  - invalid angle value
  - malformed timestamp
- `401 Unauthorized`
  - missing `device_id`
  - missing `X-API-Key`
  - invalid device/API key pair

## Operational Notes for IoT Projects

When adapting this gateway for the real uFlex deployment, consider the following:

- **Credential management**: replace hard-coded development credentials with a
  secure enrollment or provisioning flow tied to the Device bounded context.
- **Persistence**: SQLite is suitable for local development and lightweight
  edge deployments, but not ideal for high-write concurrency.
- **Observability**: add structured logging, trace correlation, and a proper
  health check endpoint before production use.
- **Device contracts**: version telemetry payloads carefully so kit firmware
  and server-side ingestion remain compatible.
- **Startup lifecycle**: move bootstrap logic out of `before_request` if you
  need deterministic initialization during container startup.

## Documentation

Additional documentation is available in [`docs/`](docs):

- [`docs/user-stories.md`](docs/user-stories.md): technical stories and
  acceptance criteria for unattended kit-to-gateway interactions.
- [`docs/class-diagram.puml`](docs/class-diagram.puml): PlantUML diagram of
  the bounded contexts, layers, and relationships.

## License

This project is licensed under the MIT License. See [`LICENSE.md`](LICENSE.md)
for details.
