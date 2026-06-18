# Technical Stories — uFlex Edge Gateway

## Overview

This document captures the technical stories for the uFlex Edge Gateway, an IoT
edge application that receives range-of-motion telemetry from uFlex IoT Kits
through HTTP endpoints. In this context, interactions are unattended: each kit
submits movement records autonomously during a rehabilitation session, without
direct end-user participation at the moment of transmission.

The stories are written from the perspective of a uFlex IoT Kit maker. This
perspective emphasizes the integration contract on which the kit and its
firmware depend, including authentication, telemetry validation, timestamp
handling, persistence guarantees, and service readiness.

The acceptance criteria focus on observable edge-gateway behavior rather than
user interface details. They reflect the current implemented scope of the
solution and align with the Domain-Driven Design approach used in the project,
particularly the Monitoring and IAM bounded contexts and their domain,
application, infrastructure, and interface layers.

### TS-UEG-001 — Ingest an Authenticated Movement Record
As a uFlex IoT Kit maker, I want each kit to submit joint flexion readings autonomously to the movement ingestion endpoint so that the edge gateway validates and persists each record reliably.

Acceptance criteria:
- Scenario: Successful create
  - Given a uFlex IoT Kit submits a `POST` request to `/api/v1/movement-monitoring/data-records`
  - And the request includes the required telemetry attributes
  - And the request includes valid kit credentials
  - When the edge gateway validates and persists the movement record
  - Then the edge gateway returns a response with status `201 Created`
  - And the response includes the created record with `id`, `device_id`, `angle`, and `created_at`

- Scenario: Missing required fields
  - Given a uFlex IoT Kit submits a `POST` request to `/api/v1/movement-monitoring/data-records`
  - And the request omits a required telemetry attribute
  - When the edge gateway validates the payload
  - Then the edge gateway returns a response with status `400 Bad Request`
  - And the response includes an error payload describing missing required fields

---

### TS-UEG-002 — Enforce Kit Authentication by API Key
As a uFlex IoT Kit maker, I want each kit request to be authenticated with an API key so that only registered kits can submit telemetry to the edge gateway.

Acceptance criteria:
- Scenario: Missing authentication data
  - Given a uFlex IoT Kit submits a request to a protected endpoint
  - And the request omits the required kit credentials
  - When the edge gateway executes IAM authentication
  - Then the edge gateway returns a response with status `401 Unauthorized`
  - And the response indicates missing `device_id` or `X-API-Key`

- Scenario: Invalid credential pair
  - Given a uFlex IoT Kit submits a request to a protected endpoint
  - And the device identifier and API key do not match any registered kit
  - When the edge gateway executes IAM authentication
  - Then the edge gateway returns a response with status `401 Unauthorized`
  - And the response indicates an invalid device ID or API key

---

### TS-UEG-003 — Validate Flexion Angle Domain Rules
As a uFlex IoT Kit maker, I want the gateway to validate flexion angle values sent by each kit against domain constraints so that invalid range-of-motion data is rejected before persistence.

Acceptance criteria:
- Scenario: Angle outside the accepted range
  - Given a uFlex IoT Kit submits a `POST` request to `/api/v1/movement-monitoring/data-records`
  - And the `angle` value is outside the range `0..360`
  - When the domain service validates the payload
  - Then the edge gateway returns a response with status `400 Bad Request`
  - And the response includes an error payload for invalid data format

- Scenario: Angle is not numeric
  - Given a uFlex IoT Kit submits a `POST` request to `/api/v1/movement-monitoring/data-records`
  - And the `angle` value is not numeric
  - When the domain service attempts to parse `angle`
  - Then the edge gateway returns a response with status `400 Bad Request`
  - And the response includes an error payload for invalid data format

---

### TS-UEG-004 — Normalize Kit Timestamps to UTC
As a uFlex IoT Kit maker, I want the gateway to normalize timestamps sent by each kit to UTC so that stored telemetry remains consistent across kit time zones.

Acceptance criteria:
- Scenario: Timestamp provided with time-zone offset
  - Given a uFlex IoT Kit submits a `POST` request to `/api/v1/movement-monitoring/data-records`
  - And the `created_at` value is provided in valid ISO 8601 format with an offset
  - When the edge gateway parses the timestamp through the domain service
  - Then the value is converted and stored as UTC
  - And the response includes the normalized `created_at` value

- Scenario: Timestamp omitted
  - Given a uFlex IoT Kit submits a `POST` request to `/api/v1/movement-monitoring/data-records`
  - And the request omits `created_at`
  - When the edge gateway creates the movement record through the domain service
  - Then `created_at` is set using the current UTC time
  - And the record is persisted with that generated timestamp

---

### TS-UEG-005 — Persist Accepted Movement Records
As a uFlex IoT Kit maker, I want each accepted telemetry record from a kit to become durable and identifiable so that ingestion remains reliable and traceable.

Acceptance criteria:
- Scenario: Accepted record becomes durable
  - Given the edge gateway holds a valid `MovementRecord` domain entity without an `id`
  - When the edge gateway completes persistence
  - Then the record is stored in local persistence
  - And the returned domain entity includes the assigned `id`

- Scenario: Application service orchestrates domain and persistence
  - Given a uFlex IoT Kit submits a valid authenticated request
  - And the request contains accepted `angle` and timestamp values
  - When the edge gateway executes the create-movement-record use case
  - Then it validates the kit through the IAM repository
  - And it delegates entity creation to the domain service
  - And it persists the record through the movement repository

---

### TS-UEG-006 — Bootstrap Database and Seed Test Kit on First Request
As a uFlex IoT Kit maker, I want the edge gateway to prepare its local storage on the first request so that a kit can begin sending records without manual database preparation.

Acceptance criteria:
- Scenario: First request bootstraps storage
  - Given the edge gateway receives its first HTTP request after startup
  - When the edge gateway executes its startup setup hook
  - Then local storage is initialized
  - And the required storage structures are created if missing
  - And the default test kit (`uflex-kit-001`) is made available if absent

- Scenario: Subsequent requests skip bootstrap work
  - Given the edge gateway already handled at least one request in the current process
  - When another request is received
  - Then the edge gateway does not run initialization again
  - And request handling proceeds without repeating bootstrap operations

---

## Story-to-Context Mapping

- **Monitoring bounded context**: `TS-UEG-001`, `TS-UEG-003`, `TS-UEG-004`, `TS-UEG-005`
- **IAM bounded context**: `TS-UEG-002`
- **Application bootstrap / shared infrastructure**: `TS-UEG-006`
