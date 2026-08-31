# FoodRescue AI — Technical Specification

## 1. Purpose

FoodRescue AI is an autonomous, agentic surplus food rescue coordination platform designed to eliminate perishable food waste and accelerate meal delivery to food-insecure communities across Sri Lanka. The system coordinates three distinct stakeholder groups in real time:

1. **Food Donors:** Commercial restaurants, hotel banquets, caterers, bakeries, supermarkets, and households with surplus food.
2. **Recipient Organizations:** Charitable shelters, orphanages, elder care homes, community kitchens, and relief organizations.
3. **Volunteer Couriers:** Civic volunteers operating motorbikes, three-wheelers (tuk-tuks), cars, vans, or bicycles available for immediate dispatch.

The primary user communication channel is **WhatsApp**, backed by **Agent Kernel**, **Google Gemini**, and a production **Supabase PostgreSQL** database. Operations personnel monitor real-time pipeline status, volunteer locations, and message threads via a centralized web dashboard hosted on **Vercel**.

---

## 2. System Architecture & Visual Workflow Reference

### Visual Workflow Reference

The canonical visual workflow for FoodRescue AI is shown below:

![FoodRescue AI End-to-End Workflow](docs/images/foodrescue-workflow.png)

### Architectural Components

```
                                 ┌─────────────────────────────┐
                                 │    WhatsApp User Devices    │
                                 │  (Donors, Orgs, Volunteers) │
                                 └──────────────┬──────────────┘
                                                │ HTTPS / Webhook
                                                ▼
                                 ┌─────────────────────────────┐
                                 │   Meta WhatsApp Cloud API   │
                                 │      (Graph API v24.0)      │
                                 └──────────────┬──────────────┘
                                                │ POST /whatsapp/webhook
                                                ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                             FoodRescue AI Backend (ASGI)                                │
│                                                                                         │
│  ┌───────────────────────┐      ┌─────────────────────────┐     ┌────────────────────┐  │
│  │ WhatsApp Webhook      │─────►│ Agent Kernel            │────►│ Google ADK         │  │
│  │ (whatsapp_handler.py) │      │ ChatService / RESTAPI   │     │ (foodrescue_       │  │
│  └───────────────────────┘      └────────────┬────────────┘     │  coordinator)      │  │
│                                              │                  └─────────┬──────────┘  │
│  ┌───────────────────────┐                   │                            │             │
│  │ Web Dashboard API     │◄──────────────────┤                            │             │
│  │ (api_routes.py)       │                   ▼                            ▼             │
│  └───────────────────────┘      ┌─────────────────────────┐     ┌────────────────────┐  │
│                                 │ Resilient Executor      │◄────│ 35+ Bound Tools    │  │
│  ┌───────────────────────┐      │ (Model Pool & Fallback) │     │ (tools.py)         │  │
│  │ QR Verification UI    │      └────────────┬────────────┘     └─────────┬──────────┘  │
│  │ (qr_service.py)       │                   │                            │             │
│  └───────────────────────┘                   ▼                            ▼             │
│                                 ┌────────────────────────────────────────────────────┐  │
│                                 │ Database Repository Layer (database.py)            │  │
│                                 └─────────────────────┬──────────────────────────────┘  │
└───────────────────────────────────────────────────────┼─────────────────────────────────┘
                                                        │ Connection Pool
                                                        ▼
                                 ┌─────────────────────────────────────────────────────┐
                                 │           Supabase PostgreSQL Database              │
                                 │  (13 Production Tables, Constraints, Indexes, RLS)  │
                                 └─────────────────────────────────────────────────────┘
```

The system is organized into decoupled layers:
* **Ingress Layer:** Handles Meta WhatsApp Cloud API webhooks (`/whatsapp/webhook`), verifies HMAC signatures, and deduplicates incoming message IDs.
* **Agent Orchestration Layer:** Agent Kernel (`agentkernel.core.ChatService`) routes incoming conversations to the `foodrescue_coordinator` agent powered by Google ADK (`google-adk`).
* **Resilient Execution Engine:** `resilient_executor.py` manages automatic LLM model rotation (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.6-flash`), handles rate limits (HTTP 429), and provides deterministic rule fallback for zero-downtime execution.
* **Persistence Layer:** `database.py` dispatches operations to `db_supabase.py` (Supabase PostgreSQL) with connection pooling and keepalive protection.
* **Logistics & Verification Layer:** `routing_service.py` provides turn-by-turn road routing via GraphHopper API, while `qr_service.py` manages cryptographic physical handover tokens and camera scanner rendering.

---

## 3. User Roles

The system enforces strict role isolation across four primary actors:

| Role | Interface | Primary Responsibilities | Data Collected |
|---|---|---|---|
| **Food Donor** | WhatsApp | Submitting surplus food offers, confirming donation summaries, providing pickup address/live GPS location pin, displaying Pickup QR code to courier. | Name, phone, organization/business name, food type, quantity, unit, dietary info, pickup location/GPS pin, pickup deadline. |
| **Recipient Organization** | WhatsApp | Registering charity profile, accepting matching donation offers, approving assigned couriers, displaying Delivery QR code to courier upon arrival. | Organization name, phone, district/service area, accepted food types, daily portion capacity, operating hours, delivery location. |
| **Volunteer Courier** | WhatsApp + Web Camera Scanner | Registering courier profile, sharing availability (`AVAILABLE`/`BUSY`), receiving structured task offers, accepting/rejecting tasks, navigating routes, scanning donor Pickup QR, scanning organization Delivery QR. | Name, phone, transport mode (Motorbike, Tuk-Tuk, Car, Van, Bicycle), vehicle capacity, service area, live GPS coordinates, completed trips. |
| **Administrator / Dispatcher** | Web Dashboard | Monitoring live operations pipeline, reviewing active donations, viewing real-time map markers, inspecting conversation transcripts, managing transport reimbursement rates. | System-wide aggregated statistics, active audit logs, notification feeds, session cache states. |

---

## 4. WhatsApp Communication

### Webhook Architecture

* **Verification Endpoint (`GET /whatsapp/webhook`):** Handles Meta Cloud API webhook verification challenge using `hub.mode`, `hub.verify_token`, and `hub.challenge`.
* **Event Ingestion (`POST /whatsapp/webhook`):** Ingests incoming WhatsApp events (text messages, audio voice notes, GPS location pins, interactive button replies).
* **Security & Authentication:** Validates the `X-Hub-Signature-256` HTTP header against `WHATSAPP_APP_SECRET` using HMAC SHA-256.
* **Idempotency Ring Buffer:** Employs an in-memory FIFO cache (`PROCESSED_MESSAGE_IDS`, max capacity 2000) combined with database persistence to prevent duplicate processing from Meta webhook retries.
* **Session Mapping:** Maps every conversation to an isolated session key: `whatsapp:<normalized_phone_number>`.

### Message Delivery

* Uses Meta WhatsApp Graph API v24.0 (`https://graph.facebook.com/v24.0/{phone_number_id}/messages`).
* Long messages exceeding 4,096 characters are automatically chunked and delivered sequentially.
* Outgoing image messages (`/api/qr/{token}.png`) include structured verification instructions and fallback links.

---

## 5. Conversation State Management

FoodRescue AI implements a stateful conversational engine that avoids repetitive questioning:

```
                            User Sends Message
                                    │
                                    ▼
                     Lookup User Record in DB (users table)
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
            Existing User Profile            New / Guest User
                    │                               │
                    └───────────────┬───────────────┘
                                    │
                     Check Active Draft & Conversation State
                                    │
               ┌────────────────────┼────────────────────┐
               ▼                    ▼                    ▼
        DONOR WORKFLOW         ORGANIZATION          VOLUNTEER
       (Draft Slot-Fill)       (Offer Match)      (Dispatch Claim)
```

### Zero-Repetition Engine (`get_next_missing_donation_field`)

When a donor provides partial donation information (e.g. *"I have 25 rice packets"*), the engine determines the next missing field in strict order without asking for previously stored profile data:

1. `FOOD_TYPE`: Type of food (e.g., Prepared Meals, Rice & Curry, Sandwiches, Bread).
2. `QUANTITY`: Numerical quantity and portion count.
3. `DONOR_NAME`: Name or restaurant/hotel business name (skipped if present in user profile).
4. `DISTRICT`: Administrative district (e.g., Colombo, Kandy, Gampaha; skipped if known).
5. `DEADLINE`: Pickup availability deadline (e.g., "Before 8 PM", "Within 2 hours").
6. `WHATSAPP_LOCATION`: WhatsApp live GPS location pin (`📎/➕ → Location → Send your current location`).
7. `CONFIRMATION`: Generates summary confirmation card before database insertion.

### Multilingual State

Language preference (`en`, `si`, `ta`) and response mode (`text`, `voice`) are persisted in the `users` table and preserved across all future sessions.

---

## 6. Donor Workflow

1. **Initiation:** Donor messages WhatsApp with intent or selects option `1` from the main menu.
2. **Entity Extraction:** Natural language processing parses food type, quantity, unit, dietary notes, location, and deadline from text or audio voice messages.
3. **Draft Storage:** Extracted slots are persisted in `users.active_draft`.
4. **Interactive Location Sharing:** The donor is prompted to share their WhatsApp location pin for accurate GPS dispatch.
5. **Confirmation Summary:** A summary card is displayed:
   ```text
   📦 Donation Summary
   • Food: 30 portions of Vegetable Fried Rice (Vegetarian)
   • Location: Colombo 03
   • Available Until: 8:00 PM
   
   Reply Confirm to create the donation, or tell me what to change.
   ```
6. **Matching & Notification:** Upon confirmation, the donation status is set to `AVAILABLE`, and proximity-ranked offer requests are broadcast to recipient organizations in the district.

---

## 7. Organization Workflow

1. **Registration:** Recipient organization registers via WhatsApp (name, service area, accepted food types, daily capacity, delivery location).
2. **Offer Broadcast:** When a matching donation is published in their district, the organization receives an offer notification:
   ```text
   🏢 New Food Donation Available in Colombo!
   • Food: 30 portions of Vegetable Fried Rice
   • Donor: Cinnamon Grand Kitchen (Colombo 03)
   • Distance: ~3.2 km
   • Collect Before: 8:00 PM
   
   Reply Accept to claim this donation for your shelter.
   ```
3. **Acceptance:** Organization replies `Accept` → Task transitions to `MATCHED` / `ASSIGNED`.
4. **Courier Assignment:** Organization receives courier details (name, transport mode, phone, estimated arrival time) and approves courier dispatch.
5. **Delivery QR Code:** Upon courier arrival, organization presents the Delivery QR code (`FR-DL-...`) on their phone screen.

---

## 8. Volunteer Workflow

1. **Registration & Status:** Volunteer registers vehicle type (Motorbike, Three-Wheeler, Car, Van, Bicycle) and service area.
2. **Availability Toggle:** Replying `AVAILABLE` marks the volunteer as active in the district; replying `BUSY` pauses dispatch notifications.
3. **Task Opportunity Offer:** Structured task offer sent to the nearest available volunteer:
   ```text
   🚚 Food Pickup Opportunity in Colombo!
   • Task ID: task-c8f2a1
   • Food: 30 portions of Vegetable Fried Rice
   • Pickup: Cinnamon Grand, Colombo 03
   • Delivery: Hope Community Shelter, Colombo 05
   • Distance: ~4.5 km
   • Transport Support: LKR 450
   
   Reply Accept or Reject
   ```
4. **Task Acceptance:** Volunteer replies `Accept` → Status set to `BUSY`, task set to `EN_ROUTE`.
5. **Turn-by-Turn Navigation:** System sends Google Maps / OpenStreetMap directions link to the donor location.
6. **Pickup QR Scan:** Volunteer scans donor's screen via camera scanner URL (`/scanner?type=pickup&task_id=...`).
7. **Delivery QR Scan:** Volunteer travels to the recipient shelter and scans organization's screen (`/scanner?type=delivery&task_id=...`).

---

## 9. Donation Lifecycle

```
┌─────────────┐     Org Accepts Match     ┌─────────────┐     Volunteer Assigned     ┌─────────────────┐
│  AVAILABLE  │──────────────────────────►│   MATCHED   │───────────────────────────►│ PICKUP_ASSIGNED │
└──────┬──────┘                           └──────┬──────┘                            └────────┬────────┘
       │                                         │                                            │
       │ Donor Cancels                           │ Timeout / No Vol                           │ Courier Scans
       ▼                                         ▼                                            ▼ Pickup QR
┌─────────────┐                           ┌─────────────┐                            ┌─────────────────┐
│  CANCELLED  │                           │   EXPIRED   │                            │    COLLECTED    │
└─────────────┘                           └─────────────┘                            └────────┬────────┘
                                                                                              │
                                                                                              │ Courier Scans
                                                                                              ▼ Delivery QR
                                                                                     ┌─────────────────┐
                                                                                     │    DELIVERED    │
                                                                                     └─────────────────┘
```

---

## 10. Pickup Lifecycle

```
┌─────────────┐     Volunteer Accepts Task     ┌──────────────┐     Courier In Transit     ┌──────────────┐
│   PENDING   │───────────────────────────────►│   ASSIGNED   │───────────────────────────►│   EN_ROUTE   │
└─────────────┘                                └──────────────┘                            └──────┬───────┘
                                                                                                  │
                                                                                                  │ Scan Pickup QR
                                                                                                  ▼
┌─────────────┐     Reimbursement Recorded     ┌──────────────┐     Scan Delivery QR       ┌──────────────┐
│  COMPLETED  │◄───────────────────────────────│  DELIVERED   │◄───────────────────────────│  COLLECTED   │
└─────────────┘                                └──────────────┘                            └──────────────┘
```

---

## 11. QR Pickup Verification

1. **Token Generation:** When a pickup task is assigned, `qr_service.py` generates a cryptographically random token (`FR-PK-{secrets.token_hex(6)}`) stored in `qr_codes` table with `status='ACTIVE'`, `qr_type='PICKUP'`, and a 6-hour expiration timestamp.
2. **Image Delivery:** Donor receives an image message via Meta Graph API pointing to `/api/qr/{token}.png`.
3. **Scanner Interface:** Volunteer opens `/scanner?type=pickup&task_id={task_id}` on mobile (utilizing `html5-qrcode` library) or accesses the verification link `/verify/pickup/{token}`.
4. **Atomic Verification:** Volunteer clicks "Confirm Food Pickup". The endpoint `POST /verify/pickup/{token}`:
   * Validates token existence, status (`ACTIVE`), and expiration.
   * Updates `qr_codes.status` to `'VERIFIED'` and records `verified_at` timestamp.
   * Transitions `pickup_tasks.status` to `'COLLECTED'` and `donations.status` to `'COLLECTED'`.
   * Dispatches WhatsApp notification to Donor: *"Food Collected! Courier has picked up your donation."*
   * Dispatches WhatsApp notification to Organization: Courier en route with Delivery QR image attached.

---

## 12. QR Delivery Verification

1. **Token Generation:** Upon successful pickup verification, `qr_service.py` generates a Delivery token (`FR-DL-{secrets.token_hex(6)}`) stored in `qr_codes` with `status='ACTIVE'` and `qr_type='DELIVERY'`.
2. **Image Delivery:** Recipient organization receives the Delivery QR image on WhatsApp.
3. **Scanner Interface:** Volunteer opens `/scanner?type=delivery&task_id={task_id}` or accesses `/verify/delivery/{token}`.
4. **Atomic Verification:** Volunteer clicks "Confirm Food Delivery". The endpoint `POST /verify/delivery/{token}`:
   * Validates token existence and status.
   * Updates `qr_codes.status` to `'VERIFIED'` and records `verified_at`.
   * Transitions `pickup_tasks.status` to `'DELIVERED'` and `'COMPLETED'`.
   * Transitions `donations.status` to `'DELIVERED'`.
   * Inserts reimbursement record in `reimbursements` table with calculated transport support amount.
   * Dispatches completion notifications to Donor, Organization, and Volunteer.

---

## 13. Matching and Routing

### Proximity & Road Routing

* **Primary Engine (`routing_service.py`):** Integrates with the GraphHopper Routing API for real-world road networks, travel durations, and GeoJSON polylines.
* **Secondary Fallback (`routing.py`):** Computes Haversine great-circle distance with a 1.25x road winding factor.
* **Geocoding Registry:** Contains coordinate bounding boxes for all 25 Sri Lankan administrative districts and 100+ cities/suburbs.

### Dynamic Transport Reimbursement

Reimbursement amounts are calculated using vehicle-specific rates:

$$\text{Reimbursement (LKR)} = \text{Base Fare} + (\text{Distance (km)} \times \text{Rate per km})$$

| Transport Mode | Base Fare (LKR) | Rate / km (LKR) | Max Portion Capacity |
|---|---|---|---|
| **Motorbike** | 50.0 | 50.0 | 25 portions |
| **Three-Wheeler (Tuk-Tuk)** | 100.0 | 90.0 | 60 portions |
| **Car** | 150.0 | 80.0 | 150 portions |
| **Van** | 250.0 | 120.0 | 500 portions |
| **Bicycle / E-Bike** | 0.0 | 25.0 | 10 portions |

---

## 14. Supabase PostgreSQL Architecture

The canonical schema is defined in `supabase/migrations/20260827000000_create_foodrescue_schema.sql`:

```sql
-- 1. Donors
CREATE TABLE donors (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(64),
    organization_name VARCHAR(255),
    location TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Recipient Organizations
CREATE TABLE organizations (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(64),
    service_area TEXT NOT NULL,
    accepted_food_types TEXT NOT NULL,
    capacity VARCHAR(128),
    availability VARCHAR(128) DEFAULT 'daytime',
    location TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Volunteers / Couriers
CREATE TABLE volunteers (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(64),
    service_area TEXT NOT NULL,
    availability VARCHAR(255),
    current_status VARCHAR(64) NOT NULL DEFAULT 'available',
    location TEXT NOT NULL,
    transport_mode VARCHAR(64) DEFAULT 'Motorbike',
    availability_status VARCHAR(64) DEFAULT 'AVAILABLE',
    current_location TEXT,
    current_coordinates JSONB,
    vehicle_capacity INTEGER DEFAULT 25,
    completed_pickups INTEGER DEFAULT 0,
    last_available_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Food Donations
CREATE TABLE donations (
    id VARCHAR(64) PRIMARY KEY,
    donor_id VARCHAR(64) NOT NULL REFERENCES donors(id) ON DELETE CASCADE,
    food_type VARCHAR(255) NOT NULL,
    quantity NUMERIC(10, 2) NOT NULL CHECK (quantity > 0),
    unit VARCHAR(64) NOT NULL,
    dietary_information TEXT,
    pickup_location TEXT NOT NULL,
    available_from VARCHAR(128) NOT NULL,
    pickup_deadline VARCHAR(128) NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'AVAILABLE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5. Pickup & Delivery Tasks
CREATE TABLE pickup_tasks (
    id VARCHAR(64) PRIMARY KEY,
    donation_id VARCHAR(64) NOT NULL REFERENCES donations(id) ON DELETE CASCADE,
    organization_id VARCHAR(64) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    volunteer_id VARCHAR(64) REFERENCES volunteers(id) ON DELETE SET NULL,
    pickup_location TEXT NOT NULL,
    pickup_coordinates JSONB,
    pickup_location_confirmed BOOLEAN DEFAULT FALSE,
    delivery_location TEXT NOT NULL,
    destination_coordinates JSONB,
    destination_location_confirmed BOOLEAN DEFAULT FALSE,
    pickup_distance_km NUMERIC(10, 2) DEFAULT 0.0,
    pickup_duration_minutes INTEGER DEFAULT 0,
    delivery_distance_km NUMERIC(10, 2) DEFAULT 0.0,
    delivery_duration_minutes INTEGER DEFAULT 0,
    total_distance_km NUMERIC(10, 2) DEFAULT 0.0,
    estimated_transport_cost NUMERIC(10, 2) DEFAULT 0.0,
    approved_transport_reimbursement NUMERIC(10, 2) DEFAULT 0.0,
    delivery_status VARCHAR(64) DEFAULT 'PENDING',
    volunteer_accepted_at TIMESTAMPTZ,
    food_collected_at TIMESTAMPTZ,
    food_delivered_at TIMESTAMPTZ,
    scheduled_time VARCHAR(128) NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. Notifications
CREATE TABLE notifications (
    id VARCHAR(64) PRIMARY KEY,
    recipient_type VARCHAR(64) NOT NULL,
    recipient_id VARCHAR(64) NOT NULL,
    message TEXT NOT NULL,
    channel VARCHAR(64) NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'SENT',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 7. Audit Events
CREATE TABLE audit_events (
    id VARCHAR(64) PRIMARY KEY,
    event_type VARCHAR(128) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    related_id VARCHAR(64),
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 8. Reimbursements
CREATE TABLE reimbursements (
    id VARCHAR(64) PRIMARY KEY,
    pickup_task_id VARCHAR(64) NOT NULL REFERENCES pickup_tasks(id) ON DELETE CASCADE,
    volunteer_id VARCHAR(64) NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
    distance_km NUMERIC(10, 2) NOT NULL,
    rate_per_km NUMERIC(10, 2) NOT NULL,
    transport_mode VARCHAR(64) NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    currency VARCHAR(16) NOT NULL DEFAULT 'LKR',
    status VARCHAR(64) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    notes TEXT
);

-- 9. Pickup Location History (GPS Breadcrumbs)
CREATE TABLE pickup_location_history (
    id VARCHAR(64) PRIMARY KEY,
    pickup_task_id VARCHAR(64) NOT NULL REFERENCES pickup_tasks(id) ON DELETE CASCADE,
    volunteer_id VARCHAR(64) NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
    latitude NUMERIC(10, 7) NOT NULL,
    longitude NUMERIC(10, 7) NOT NULL,
    accuracy_m NUMERIC(10, 2),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 10. Persistent Users & Profiles
CREATE TABLE users (
    phone_number VARCHAR(64) PRIMARY KEY,
    display_name VARCHAR(255),
    preferred_language VARCHAR(32) DEFAULT 'en',
    preferred_response_mode VARCHAR(32) DEFAULT 'text',
    user_role VARCHAR(64) DEFAULT 'unknown',
    default_location TEXT,
    active_donation_id VARCHAR(64),
    active_task_id VARCHAR(64),
    conversation_state JSONB DEFAULT '{}'::jsonb,
    active_draft JSONB DEFAULT '{}'::jsonb,
    onboarding_completed BOOLEAN DEFAULT FALSE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb
);

-- 11. Messages
CREATE TABLE messages (
    id VARCHAR(64) PRIMARY KEY,
    phone_number VARCHAR(64) NOT NULL,
    sender VARCHAR(64) NOT NULL,
    message_text TEXT NOT NULL,
    is_voice BOOLEAN DEFAULT FALSE,
    transcript TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 12. System Settings
CREATE TABLE system_settings (
    setting_key VARCHAR(128) PRIMARY KEY,
    setting_value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 13. Physical Handover QR Codes
CREATE TABLE qr_codes (
    id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES pickup_tasks(id) ON DELETE CASCADE,
    donation_id VARCHAR(64) NOT NULL REFERENCES donations(id) ON DELETE CASCADE,
    qr_type VARCHAR(32) NOT NULL,
    token VARCHAR(255) UNIQUE NOT NULL,
    token_hash VARCHAR(255),
    donor_id VARCHAR(64) REFERENCES donors(id) ON DELETE SET NULL,
    organization_id VARCHAR(64) REFERENCES organizations(id) ON DELETE SET NULL,
    assigned_volunteer_id VARCHAR(64) REFERENCES volunteers(id) ON DELETE SET NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    verified_at TIMESTAMPTZ,
    verified_by VARCHAR(128),
    metadata JSONB DEFAULT '{}'::jsonb
);
```

---

## 15. API Endpoints

### Core Platform & Webhook Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Application health check and backend connection status |
| `GET` | `/whatsapp/webhook` | Meta WhatsApp Cloud API webhook challenge verification |
| `POST` | `/whatsapp/webhook` | Meta WhatsApp Cloud API incoming message processing |
| `POST` | `/api/v1/chat` | Direct Agent Kernel conversational execution endpoint |
| `GET` | `/api/v1/agents` | List registered Agent Kernel agent identifiers |

### Operational Dashboard Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/dashboard`, `/api/stats` | Aggregated metrics, KPI counts, and operational summary |
| `GET` | `/api/live-operations` | Real-time 7-stage pipeline operations feed |
| `GET` | `/api/donations` | List all donations (supports `?status=` filter) |
| `POST` | `/api/donations` | Create new donation directly from dashboard |
| `GET` | `/api/donations/{id}` | Detailed donation record with linked task, donor, and recipient |
| `DELETE` | `/api/donations/{id}` | Permanently delete donation record |
| `GET` | `/api/organizations` | List registered recipient organizations |
| `GET` | `/api/volunteers` | List registered volunteer couriers |
| `POST` | `/api/volunteers` | Register volunteer courier from dashboard |
| `POST` | `/api/volunteers/{id}/location`| Update live volunteer GPS coordinates and recalculate active route |
| `GET` | `/api/pickups` | List all pickup tasks with dynamically calculated logistics |
| `GET` | `/api/users` | List persistent WhatsApp users with language and state |
| `GET` | `/api/conversations` | List active WhatsApp conversation threads |
| `GET` | `/api/conversations/{phone}/messages`| Chronological message history for a phone number |
| `POST` | `/api/conversations/{phone}/simulate`| Inject simulated user message for live testing |
| `GET` | `/api/agent-events` | Operational audit event stream |
| `GET` | `/api/reports` | Environmental and nutritional impact analytics |
| `POST` | `/api/settings` | Update dynamic transport reimbursement rates |

### QR Verification & Routing Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/qr/{token}.png` | Generate and stream high-resolution QR PNG image |
| `GET` | `/verify/pickup/{token}` | Mobile-first Pickup Handover verification page |
| `POST` | `/verify/pickup/{token}` | Atomically confirm pickup handover and dispatch notifications |
| `GET` | `/verify/delivery/{token}` | Mobile-first Delivery Handover verification page |
| `POST` | `/verify/delivery/{token}` | Atomically confirm delivery handover and compute reimbursement |
| `GET` | `/scanner`, `/scanner/{type}` | Zero-dependency camera QR scanner web interface |
| `POST` | `/api/routes/calculate` | Calculate road route distance, duration, and geometry |
| `POST` | `/api/routes/pickup-route` | Calculate two-leg route (`Volunteer → Donor → Recipient`) |
| `GET` | `/api/tasks/{id}/route` | Active dynamic route for a task based on live GPS |

---

## 16. Dashboard Architecture

* **Framework:** Vanilla HTML5, CSS3, and JavaScript Single Page Application (`static/index.html`, `static/styles.css`, `static/app.js`).
* **Design System:** Dark-themed modern UI utilizing CSS custom properties, grid layouts, and micro-animations.
* **Mapping:** Integrated **Leaflet.js** map rendering live interactive markers for donors, organizations, and transit routes.
* **Live Synchronization:** 4-second background polling cycle updating KPIs, pipeline stages, and message logs without full page reloads.
* **WhatsApp Simulator:** Interactive modal enabling judges and operators to simulate real WhatsApp conversations from any phone number.

---

## 17. Agent Kernel Integration

FoodRescue AI is implemented as an Agent Kernel extension:

```python
# app.py
from agentkernel.adk import GoogleADKModule, GoogleADKToolBuilder
from google.adk.agents import Agent
import tools

# Tool Binding
BOUND_TOOLS = GoogleADKToolBuilder.bind([
    tools.create_donation,
    tools.update_donation_details,
    tools.get_donation,
    tools.find_matching_organizations,
    tools.accept_donation,
    tools.find_available_volunteers,
    tools.create_pickup_task,
    tools.assign_volunteer,
    tools.calculate_route,
    tools.calculate_pickup_route,
    tools.generate_handover_qr,
    tools.verify_handover_qr,
    # ... (35+ total operational tools)
])

# Canonical Coordinator Agent
foodrescue_coordinator = Agent(
    name="foodrescue_coordinator",
    model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
    description="FoodRescue AI Autonomous Coordinator agent",
    instruction=COORDINATOR_INSTRUCTION,
    tools=BOUND_TOOLS,
)

# Register with Agent Kernel
GoogleADKModule([foodrescue_coordinator])
```

The REST server mounts `RESTAPI.add(api_routes.get_router())` and `RESTAPI.add(whatsapp_handler.get_whatsapp_router())` to provide unified routing.

---

## 18. External Services

| Service | Protocol | Configuration Variable | Failure Strategy |
|---|---|---|---|
| **Google Gemini** | Google GenAI SDK | `GEMINI_API_KEY`, `GEMINI_MODEL` | Multi-model pool rotation (`flash-lite` → `flash`), rate-limit catch (429), deterministic rule fallback |
| **Meta WhatsApp API** | HTTPS / REST (Graph API v24.0) | `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Mock delivery mode for offline local development; automatic payload chunking |
| **Supabase PostgreSQL** | PostgreSQL Wire Protocol / REST | `SUPABASE_DB_URL`, `SUPABASE_URL`, `SUPABASE_KEY` | Connection pool keepalive; fallback to local SQLite for offline unit tests |
| **GraphHopper Routing** | HTTPS / REST | `GRAPHHOPPER_API_KEY` | In-memory 1-hour route caching; automatic fallback to internal Haversine geocoding registry |
| **QRCoder V4 API** | HTTPS / REST | `QRCODER_API_KEY` | In-memory PNG byte caching; automatic fallback to pure-Python zero-dependency QR engine |
| **VALSEA AI Voice** | HTTPS / REST | `VALSEA_API_KEY` | In-flow entity extraction fallback from voice transcripts |

---

## 19. Error Handling & Resilience

* **Rate Limit Failover:** When Gemini API quotas are exhausted, `resilient_executor.py` catches 429 exceptions and rotates through alternative model candidates (`gemini-3.5-flash-lite` → `gemini-3.1-flash-lite` → `gemini-3.6-flash`). If all LLM quotas are exhausted, it invokes `execute_deterministic_fallback` to process the user's intent rule-based without user disruption.
* **Webhook Retry Shielding:** Bounded ring buffer prevents repeated execution of retried Meta webhook events.
* **Graceful Degradation:** External API outages (GraphHopper, QRCoder) automatically degrade to zero-dependency local algorithms without failing requests.
* **Error Masking:** Internal stack traces, database schema details, and API keys are never returned in user conversational responses.

---

## 20. Security

* **Zero Secret Leakage:** No API tokens, Meta secrets, or database passwords are hardcoded in source code or returned in API payloads.
* **Webhook Integrity:** Incoming requests to `/whatsapp/webhook` are verified using cryptographic SHA-256 HMAC signatures against `WHATSAPP_APP_SECRET`.
* **SQL Injection Prevention:** All database operations utilize parameterized queries through psycopg/psycopg2/pg8000.
* **CORS Policy:** Strict Cross-Origin Resource Sharing restrictions configured on Vercel and local FastAPI instances.
* **Session Privacy:** Role state is strictly isolated per phone number; donor details never leak to unrelated volunteer or organization sessions.

---

## 21. Testing

The repository contains 30 test files validating all platform capabilities:

```bash
.venv\Scripts\pytest.exe -q
```

**Verified Test Results:**
```text
================== 344 passed, 4 skipped in 64.08s (0:01:04) ==================
```

### Key Test Categories
* **Core & Tool Tests (`test_foodrescue.py`):** Validates all 35+ operational tools and multi-turn workflows.
* **Role Isolation (`test_foodrescue_role_isolation_and_mongo_parity.py`):** Ensures donor, organization, and volunteer state cannot cross-contaminate.
* **Conversational Slot-Filling (`test_foodrescue_conversational_upgrade.py`):** Verifies Zero-Repetition rule and dynamic field preservation.
* **Supabase PostgreSQL Schema (`test_foodrescue_supabase.py`):** Validates table creation, foreign keys, indexes, and transactional queries.
* **QR Handover Verification (`test_foodrescue_qr_handover.py`):** Tests token generation, camera scanner endpoints, and atomic status transitions.
* **Routing & Logistics (`test_foodrescue_graphhopper_routing.py`, `test_foodrescue_dynamic_road_routing.py`):** Tests turn-by-turn road calculations and reimbursement calculations.
* **WhatsApp Cloud API (`test_foodrescue_whatsapp.py`):** Validates webhook verification, message parsing, and 3-way notifications.
* **Multilingual & Voice (`test_foodrescue_multilingual_voice.py`):** Validates English, Sinhala, and Tamil detection and translation.

---

## 22. Deployment

### Production (Vercel Serverless)

* **Entrypoint:** `api/index.py` exposes the ASGI FastAPI application instance.
* **Configuration:** `vercel.json` routes all incoming requests to `api/index.py` with 60s maximum execution duration.
* **Database Connection:** Connects directly to Supabase PostgreSQL using connection pooling (`SUPABASE_DB_URL`).

### Local Server

* **Entrypoint:** `python server.py` runs Uvicorn ASGI server on `http://0.0.0.0:8000`.
* **Tunneling for WhatsApp Webhook:** Use ngrok or Cloudflare Tunnel:
  ```bash
  ngrok http 8000
  ```
  Set the resulting HTTPS URL in the Meta Developer Portal: `https://your-tunnel.ngrok-free.app/whatsapp/webhook`.
