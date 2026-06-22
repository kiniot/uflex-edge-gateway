# uFlex Edge Gateway

`uflex_edge_gateway` is a lightweight IoT edge API for ingesting range-of-motion
telemetry emitted by uFlex IoT Kits during tele-rehabilitation sessions. The
service follows a Domain-Driven Design (DDD) approach and separates the
device-authentication concerns from the movement-telemetry ingestion concerns.

uFlex is a medical-grade tele-rehabilitation platform: patients perform guided
exercises while an IoT Kit equipped with IMU sensors measures the joint flexion
angle (range of motion). This gateway is the edge component that authenticates
each kit and reliably captures its angle readings before they are forwarded to
the cloud backend.

At its current stage, the service provides:

- device (IoT Kit) authentication using `device_id` + `X-API-Key`
- ingestion of joint flexion `angle` measurements (degrees)
- SQLite persistence through Peewee ORM
- a layered architecture aligned with DDD bounded contexts

## Current Scope

This repository currently implements a focused subset of the uFlex IoT-edge
solution:

- **Implemented**
  - registration/lookup of a development test kit
  - authentication of kit-originated requests
  - creation and persistence of movement records (flexion angle)
  - timestamp normalization to UTC
  - movement analysis: range of motion, repetition counting, min/max/mean,
    peak angular velocity and duration (`GET .../analysis`)
  - threshold evaluation against backend-supplied goals/limits, yielding an
    `actuator_action` decision
  - per-repetition quality classification (good / incomplete / unsafe)
  - series execution lifecycle: `start` / `end` / `result`, with a durable
    `serie_executions` table (good/bad reps, average ROM, valoración, danger
    flag) and raw-buffer purging
  - listing recent raw readings (`GET .../data-records`)
  - a health check endpoint (`GET /status`)
  - interactive API docs via Scalar (`GET /scalar`, `GET /openapi.json`)
- **Not implemented yet**
  - sending the `actuator_action` decision to the device (actuator transport)
  - fetching thresholds from the backend (currently passed per request)
  - forwarding the series result to the backend therapy session
  - battery / kit-status telemetry

See [`docs/movement-monitoring-api.md`](docs/movement-monitoring-api.md) for the
full request/response contract and the definition of every processed metric, and
[`docs/edge-execution-design.md`](docs/edge-execution-design.md) for the
therapy-execution model (per-repetition quality, series results, and the
remaining backend-forwarding/actuator work).

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
curl -X POST http://127.0.0.1:5000/api/v1/movement-monitoring/data-records \
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
