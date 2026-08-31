# FoodRescue AI

FoodRescue AI is an autonomous, AI-powered surplus food rescue and logistics coordination platform. Built with **Agent Kernel** and **Google Gemini (Google ADK)**, it connects food donors (restaurants, hotels, bakeries, caterers, households) with recipient organizations (charities, shelters, community kitchens) and mobilizes volunteer couriers in real time to rescue edible food before it spoils.

The primary user communication interface is **WhatsApp**, allowing donors, charities, and volunteer couriers to coordinate seamlessly without complex app installations. Operations personnel monitor real-time pipeline status, volunteer locations, and message threads via a centralized web dashboard.

---

## Live Demo

**Dashboard:** [https://foodrescue-ai-ten.vercel.app](https://foodrescue-ai-ten.vercel.app)

**WhatsApp:** +94 75 526 3482

Judges can use the WhatsApp number to interact with the FoodRescue AI conversational workflow and use the dashboard to monitor the system's live operational data.

---

## End-to-End Workflow

The diagram below illustrates the complete operational workflow of FoodRescue AI across all three roles, AI matching, dual-stage QR verification, and real-time database updates:

![FoodRescue AI End-to-End Workflow](docs/images/foodrescue-workflow.png)

---

## How Judges Can Test FoodRescue AI

Testing FoodRescue AI is simple and requires only WhatsApp on your phone and a web browser.

### 1. WhatsApp Test

* **WhatsApp Number:** **+94 75 526 3482**
* **Start Interaction:** Send **`Hi`** to begin.
* The system presents the available role options:
  * **1️⃣ Donate surplus food** (Hotels, restaurants, caterers, households)
  * **2️⃣ Request available food** (Charities, shelters, community kitchens)
  * **3️⃣ Volunteer to collect and deliver food** (Couriers & volunteers)
  * **4️⃣ Check your donation or pickup status**
  * **5️⃣ Help & Info**
  * **6️⃣ / 7️⃣ / 8️⃣ Change Language** (English, Sinhala, Tamil)

> **Natural Language & Voice:** You can also type natural requests directly (e.g., *"I have 30 vegetable rice packets in Colombo 03 available until 4 PM"*) or send voice notes in English, Sinhala, or Tamil.

### 2. Live Web Dashboard

* **Dashboard URL:** [https://foodrescue-ai-ten.vercel.app](https://foodrescue-ai-ten.vercel.app)
* Displays real-time operational data from the **Supabase PostgreSQL** production database:
  * **Live Operations Pipeline**: Real-time tracker (`Donation Available` → `Matched` → `Volunteer Dispatched` → `In Progress` → `Food Collected` → `Out for Delivery` → `Delivered & Rescued`).
  * **Operational Metrics**: Total donations, meals rescued, food weight (kg), active pickups, available volunteers, and registered organizations.
  * **Interactive Operations Map**: Leaflet map displaying active donor and organization locations across Sri Lanka.
  * **WhatsApp Conversation Feed**: Real-time log of incoming and outgoing conversational turns.

### 3. Suggested Testing Sequence

1. **Step 1 — Create a Donation (Donor Flow):**
   * Message **+94 75 526 3482** on WhatsApp with `1` or *"I have 25 lunch packets in Colombo 03"*.
   * Provide the requested food type, quantity, donor name, district/location, and pickup deadline.
   * Send your location pin when prompted, review the summary card, and reply `Confirm`.
   * The donation is saved in Supabase and matched with recipient organizations in the district.

2. **Step 2 — Register / Accept as Recipient Organization:**
   * Using a second phone or sending `2` / `Menu`, register as a recipient organization in the same district.
   * Receive the WhatsApp donation offer notification and reply `Accept` to claim the food.

3. **Step 3 — Volunteer Courier Matching & Dispatch:**
   * As a volunteer (reply `3` or *"I am available in Colombo"*), receive the pickup opportunity notification showing food details, donor location, recipient shelter, road distance, and estimated transport support (LKR).
   * Reply `Accept` to claim the task. The recipient organization receives a courier confirmation prompt and approves the dispatch.

4. **Step 4 — Pickup QR Code Verification:**
   * The donor receives a secure Pickup QR code image (`FR-PK-...`) on WhatsApp.
   * The volunteer opens the verification link or camera scanner (`/scanner/pickup`) and scans the donor's QR code.
   * The system atomically verifies the token, marks the food as `COLLECTED` / `IN_TRANSIT`, and alerts all parties.

5. **Step 5 — Delivery QR Code Verification:**
   * The volunteer follows the route navigation link to the recipient organization.
   * The organization presents the Delivery QR code image (`FR-DL-...`).
   * The volunteer scans the organization's QR code (`/scanner/delivery`).
   * The system atomically verifies delivery, marks the task as `DELIVERED` & `COMPLETED`, records the volunteer transport reimbursement, and sends completion thank-you notifications.

6. **Step 6 — Verify Live Dashboard:**
   * Refresh [https://foodrescue-ai-ten.vercel.app](https://foodrescue-ai-ten.vercel.app) to observe the updated metrics, completed delivery stage, and audit log entries.

---

## 1. Problem Statement

Every day, commercial kitchens, hotels, supermarkets, restaurants, and event caterers discard large quantities of untouched, nutritious surplus food simply because manual donation logistics are too slow, fragmented, and difficult to coordinate:

* **Urgent Expiration Windows:** Cooked meals and perishable foods spoil within narrow timeframes (2–4 hours). Without rapid coordination, edible food ends up in landfills.
* **Coordination Friction:** Donors lack dedicated staff to call multiple charities, confirm dietary requirements (halal, vegetarian), verify recipient capacity, and arrange transportation.
* **Information Asymmetry:** Recipient shelters, orphanages, and community kitchens rarely know where surplus food is available until it is too late to collect.
* **Ad-Hoc Volunteer Dispatching:** Charities lack dedicated delivery fleets and rely on ad-hoc volunteers. Without atomic task claiming, multiple drivers attempt the same pickup or tasks get abandoned.
* **Location and Verification Gaps:** Lack of accurate geocoding, turn-by-turn routing, and physical proof-of-handover leads to missed pickups, disputed deliveries, and safety concerns.
* **Language and Interface Barriers:** Kitchen staff and courier drivers in South Asia communicate primarily through WhatsApp and voice messages in Sinhala, Tamil, or English, rather than complex web forms or English-only apps.

FoodRescue AI addresses these challenges by providing an autonomous, agentic WhatsApp coordination system backed by real-time spatial routing, cryptographic QR handover verifications, and persistent database state.

---

## 2. Solution Overview

FoodRescue AI coordinates the complete surplus food recovery lifecycle across three distinct roles:

```
Donor Provides Surplus Food
    ↓
Recipient Organization Needs Food
    ↓
FoodRescue AI Matching Engine
    ↓
Suitable Volunteer Receives Pickup Opportunity
    ↓
Volunteer Accepts Offer
    ↓
Recipient Organization Reviews & Confirms Courier
    ↓
Donor Receives Pickup QR Code
    ↓
Volunteer Scans Donor's Pickup QR Code (COLLECTED)
    ↓
Volunteer Follows Turn-by-Turn Route to Organization
    ↓
Organization Displays Delivery QR Code
    ↓
Volunteer Scans Organization's Delivery QR Code (DELIVERED & COMPLETED)
    ↓
Completion Notifications Dispatched & Volunteer Reimbursement Recorded
```

### Three User Roles

#### 1. Food Donor
* Interacts entirely via WhatsApp text or voice messages.
* Provides food details: **food type**, **quantity**, **unit** (e.g. packets, portions, kg, boxes), **dietary information** (vegetarian, halal, non-veg), **pickup deadline**, and **pickup location** (text address or live WhatsApp GPS location pin).
* Receives a confirmation summary card before the donation is published.
* Receives an automated **Pickup QR Code** image when a courier is assigned.

#### 2. Recipient Organization
* Registers organization profile via WhatsApp: **organization name**, **district/service area**, **accepted food types**, **portion capacity**, and **delivery location**.
* Receives automated WhatsApp donation offer notifications when surplus food is posted in their district.
* Accepts or declines donation offers with a single reply.
* Approves the assigned volunteer courier.
* Displays the **Delivery QR Code** image upon volunteer arrival to verify delivery receipt.

#### 3. Volunteer Courier
* Registers via WhatsApp: **name**, **transport mode** (Motorbike, Three-Wheeler / Tuk-Tuk, Car / Van, Bicycle / On Foot), **service area/district**, and **availability status** (`AVAILABLE` / `BUSY`).
* Shares live location for proximity-based dispatch.
* Receives structured task offers including: Task ID, food details, donor pickup location, recipient delivery location, total road distance (km), and estimated transport support (LKR reimbursement).
* Accepts or rejects offers.
* Follows turn-by-turn map navigation links.
* Scans the Donor's QR code at pickup to confirm collection.
* Scans the Organization's QR code at delivery to complete the rescue.

---

## Dual-Stage QR Handover Verification

To guarantee food safety, chain of custody, and eliminate fraudulent handovers, FoodRescue AI implements a two-stage physical QR verification system:

```mermaid
sequenceDiagram
    autonumber
    actor D as Food Donor
    actor V as Volunteer Courier
    actor O as Recipient Organization
    participant S as FoodRescue AI (Supabase)

    Note over D,S: Stage 1: Pickup Handover Verification
    S->>D: Sends Pickup QR Code Image (FR-PK-xxxx)
    V->>D: Arrives at donor kitchen
    D->>V: Displays Pickup QR on phone screen
    V->>S: Scans QR via /verify/pickup/{token} or /scanner
    S->>S: Validates token, status -> COLLECTED / IN_TRANSIT
    S-->>D: WhatsApp: Food Collected! Thank you.
    S-->>V: WhatsApp: Pickup Confirmed. Route to Recipient sent.
    S-->>O: WhatsApp: Courier en route with Delivery QR image.

    Note over V,S: Stage 2: Delivery Handover Verification
    V->>O: Arrives at recipient organization
    O->>V: Displays Delivery QR on phone screen (FR-DL-xxxx)
    V->>S: Scans QR via /verify/delivery/{token} or /scanner
    S->>S: Validates token, status -> DELIVERED & COMPLETED
    S->>S: Calculates & records transport reimbursement (LKR)
    S-->>O: WhatsApp: Delivery completed and confirmed.
    S-->>V: WhatsApp: Delivery verified! Transport support recorded.
    S-->>D: WhatsApp: Your food has been successfully delivered!
```

1. **Pickup QR (`FR-PK-...`):**
   * Generated upon courier confirmation and sent to the donor's WhatsApp.
   * The volunteer scans the donor's screen using their phone camera via `/verify/pickup/{token}` or `/scanner?type=pickup`.
   * Verifies physical collection. Status transitions to `COLLECTED` / `IN_TRANSIT`.

2. **Delivery QR (`FR-DL-...`):**
   * Generated upon food collection and sent to the recipient organization's WhatsApp.
   * The volunteer scans the organization's screen upon arrival via `/verify/delivery/{token}` or `/scanner?type=delivery`.
   * Verifies physical receipt at the shelter. Status transitions to `DELIVERED` and `COMPLETED`. Transport reimbursement is automatically recorded.

---

## Dynamic Routing & Transport Reimbursement

* **Road Distance & Duration:** Powered by the **GraphHopper Routing API** (`routing_service.py`) with automatic fallback to Haversine straight-line distance with road-curvature adjustment (`routing.py`).
* **Multi-Point Routing:** Calculates two-leg logistics: `Volunteer Location → Donor Location → Recipient Organization`.
* **Sri Lanka Geocoding Registry:** Built-in coordinate mapping for all 25 administrative districts and major towns/suburbs across Sri Lanka.
* **Dynamic Reimbursement Engine:** Computes transport reimbursement support based on actual road distance and vehicle type:
  * **Motorbike:** Base LKR 50 + LKR 50/km
  * **Three-Wheeler / Tuk-Tuk:** Base LKR 100 + LKR 90/km
  * **Car:** Base LKR 150 + LKR 80/km
  * **Van:** Base LKR 250 + LKR 120/km
  * **Bicycle / Electric Bike:** LKR 25/km

---

## Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Agent Framework** | [Agent Kernel 0.8.1](https://kernel.yaala.ai) | Framework-agnostic agent orchestration, session context management, and tool routing |
| **Language Model** | Google Gemini (via Google ADK `google-adk>=2.7.0`) | Natural language understanding, multi-turn reasoning, and entity extraction |
| **Primary Messaging** | Meta WhatsApp Business Cloud API (Graph API v24.0) | User-facing conversational interface for text, voice notes, and location pins |
| **Production Database** | Supabase PostgreSQL | Primary persistence layer (13 relational tables, indexes, constraints, and audit logging) |
| **Web Server & REST API** | FastAPI / Starlette / Uvicorn | High-performance ASGI application hosting REST endpoints, webhooks, and dashboard |
| **Routing & Logistics** | GraphHopper Routing API + Sri Lanka Geo Registry | Real road distance, travel times, polyline geometry, and transport cost calculation |
| **QR Verification Engine** | QRCoder V4 API + Pure-Python Engine | Cryptographic handover tokens, high-res PNG image streaming, and camera scanner |
| **Speech Intelligence** | VALSEA AI Voice Service | Speech-to-text transcription for WhatsApp audio voice notes |
| **Production Hosting** | Vercel Serverless (`/api/index.py`) | Production cloud hosting for dashboard, API endpoints, and webhooks |
| **Web Dashboard** | Vanilla HTML5 / CSS3 / JavaScript + Leaflet.js | Lightweight, responsive operations monitoring and mapping interface |

---

## 3. Setup Instructions

### Prerequisites

* Python 3.10, 3.11, or 3.12
* Git
* A free [Supabase](https://supabase.com) account (for PostgreSQL database)
* A Google Gemini API key from [Google AI Studio](https://aistudio.google.com/)

### Step 1: Clone the Repository

```bash
git clone https://github.com/yaalalabs/agent-kernel.git
cd agent-kernel/use-cases/foodrescue
```

### Step 2: Set Up Python Virtual Environment

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\activate
```

**On macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables

Copy the provided `.env.example` template to `.env`:

```bash
cp .env.example .env
```

Configure `.env` with your credentials:

```ini
# Gemini LLM Credentials
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.5-flash-lite

# Persistence Configuration (Supabase PostgreSQL)
FOODRESCUE_DATABASE=supabase
FOODRESCUE_DB_BACKEND=supabase

# Supabase PostgreSQL Credentials
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your_supabase_publishable_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
SUPABASE_DB_URL=postgresql://postgres.your-project-id:your_password@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres

# Meta WhatsApp Cloud API Configuration
WHATSAPP_PHONE_NUMBER_ID=1285744151285887
WHATSAPP_BUSINESS_ACCOUNT_ID=2279553849254105
WHATSAPP_VERIFY_TOKEN=foodrescue_meta_verify_token
WHATSAPP_ACCESS_TOKEN=your_whatsapp_access_token_here

# Optional Routing & QR Services
GRAPHHOPPER_API_KEY=your_graphhopper_api_key_here
QRCODER_API_KEY=your_qrcoder_api_key_here
VALSEA_API_KEY=your_valsea_api_key_here
```

### Step 5: Initialize the Supabase PostgreSQL Database

* Open your Supabase Project Dashboard → **SQL Editor**.
* Open the migration file: `supabase/migrations/20260827000000_create_foodrescue_schema.sql`.
* Run the SQL query to create the required 13 tables, primary keys, foreign key cascades, and performance indexes.

---

## 4. How to Run the Solution

### Run the Unified Server Locally

To start the unified FastAPI server hosting the REST API, Web Dashboard, and WhatsApp webhook handler:

```bash
python server.py
```

The console will display:

```text
=================================================================
  🍲 FoodRescue AI — Unified REST API & WhatsApp Server
=================================================================
  • Host:                0.0.0.0 (http://localhost:8000)
  • Web UI:              http://localhost:8000/
  • REST API Chat:       POST http://localhost:8000/api/v1/chat
  • WhatsApp Webhook:    POST http://localhost:8000/whatsapp/webhook
  • Webhook Verify URL:  GET  http://localhost:8000/whatsapp/webhook
  • Registered Number:   +94 75 526 3482
=================================================================
```

### Open the Local Web Dashboard

Open your web browser and navigate to:
```
http://localhost:8000/
```

### Run the Agent in Interactive CLI Mode

To interact with the coordinator agent directly in your terminal:

```bash
python app.py
```

### Run the Automated Test Suite

Execute the comprehensive test suite to verify database migrations, conversational logic, QR verifications, and routing:

**On Windows:**
```powershell
.venv\Scripts\pytest.exe -q
```

**On macOS / Linux:**
```bash
pytest -q
```

**Verified Test Result:**
```text
================== 344 passed, 4 skipped in 64.08s (0:01:04) ==================
```

---

## Production Database Schema (Supabase PostgreSQL)

The active production database is **Supabase PostgreSQL**. The schema (`supabase/migrations/20260827000000_create_foodrescue_schema.sql`) consists of 13 tables:

| Table | Purpose |
|---|---|
| `donors` | Registered food donor profiles (name, phone, organization, location, created timestamp) |
| `organizations` | Recipient organizations and charities (name, phone, service area, accepted food types, capacity, location) |
| `volunteers` | Volunteer couriers (name, phone, service area, transport mode, vehicle capacity, availability status, GPS coordinates) |
| `donations` | Food donation records (donor ID, food type, quantity, unit, dietary info, pickup location, deadlines, lifecycle status) |
| `pickup_tasks` | Dispatch & pickup tasks (donation ID, organization ID, volunteer ID, locations, road distance, duration, transport cost, statuses) |
| `notifications` | System communication log for WhatsApp cross-notifications sent to donors, organizations, and volunteers |
| `audit_events` | Append-only security and operational audit trail recording all agent tool invocations and state changes |
| `reimbursements` | Volunteer transport reimbursement claims (task ID, volunteer ID, distance km, rate per km, total LKR amount, payment status) |
| `pickup_location_history` | Volunteer GPS breadcrumb location points recorded during active delivery transit |
| `users` | Persistent user profiles, language preferences (`en`, `si`, `ta`), response modes (`text`/`voice`), and draft session states |
| `messages` | Chronological WhatsApp and web message history for conversational context and dashboard audit feeds |
| `system_settings` | Dynamic configuration parameters (reimbursement rates per vehicle mode, base fares, currency) |
| `qr_codes` | Cryptographic physical handover tokens, expiration timestamps, verification timestamps, and verification actors |

> **Note on MongoDB / SQLite:** MongoDB is not the production database. Local SQLite is supported exclusively for offline unit testing when `FOODRESCUE_DATABASE=sqlite` is explicitly configured.

---

## Project Structure

```
use-cases/foodrescue/
├── api/
│   └── index.py               # Vercel serverless entrypoint with CORS & ASGI setup
├── docs/
│   └── images/
│       └── foodrescue-workflow.png  # End-to-end operational workflow diagram
├── mcp_server/                # Model Context Protocol (MCP) server integration
│   ├── server.py              # MCP server definition (stdio & SSE transports)
│   ├── location_tools.py      # GPS lookup and geocoding MCP tools
│   ├── matching_tools.py      # Recipient and volunteer matching MCP tools
│   ├── routing_tools.py       # GraphHopper routing MCP tools
│   ├── qr_tools.py            # QR generation and verification MCP tools
│   └── task_tools.py          # Operational lifecycle MCP tools
├── static/                    # Web dashboard frontend assets
│   ├── index.html             # Single Page Application dashboard UI
│   ├── styles.css             # Dark-themed responsive design system
│   ├── app.js                 # Dashboard logic, live sync, Leaflet maps, and WhatsApp simulator
│   ├── logo.svg               # Vector brand logo
│   └── favicon.svg            # Favicon
├── supabase/
│   └── migrations/
│       └── 20260827000000_create_foodrescue_schema.sql  # Canonical PostgreSQL migration
├── app.py                     # Coordinator Agent definition & GoogleADKModule registration
├── api_routes.py              # REST API endpoints, QR verification handlers, and static routing
├── database.py                # Database delegation interface
├── db_supabase.py             # Supabase PostgreSQL repository implementation
├── db_sqlite.py               # SQLite fallback repository implementation
├── db_mongo.py                # Legacy MongoDB compatibility layer
├── qr_service.py              # Cryptographic QR token generator & PNG stream engine
├── resilient_executor.py      # Resilient execution engine with model rotation & fallback
├── routing.py                 # Core routing engine, geocoding registry & rate calculations
├── routing_service.py         # GraphHopper Routing API client & polyline decoder
├── server.py                  # Local development server entrypoint
├── tools.py                   # 35+ Agent Kernel operational tools
├── translation_service.py     # Multilingual engine for English, Sinhala, and Tamil
├── voice_service.py           # Speech-to-text processing for WhatsApp voice notes
├── verify_production.py       # 18-point live production verification script
├── requirements.txt           # Python dependency requirements
├── pyproject.toml             # Project metadata and test configuration
├── vercel.json                # Vercel deployment configuration
├── .env.example               # Safe environment variable configuration template
├── README.md                  # Project overview and judging documentation
├── SPEC.md                    # Detailed technical specification
└── AGENTS.md                  # Agent architecture, database, and role isolation rules
```

---

## Troubleshooting

| Issue | Likely Cause | Solution |
|---|---|---|
| `ValueError: SUPABASE_DB_URL is missing` | Missing database configuration in `.env` | Configure `SUPABASE_DB_URL` in `.env` or set `FOODRESCUE_DATABASE=sqlite` for offline local testing. |
| `WhatsApp Webhook verification failed` | Mismatched verify token | Ensure `WHATSAPP_VERIFY_TOKEN` in `.env` matches the token configured in the Meta Developer Portal. |
| `GraphHopper API key missing` | Missing routing key | Configure `GRAPHHOPPER_API_KEY` in `.env`. The system automatically falls back to internal Haversine distance if no key is provided. |
| `Gemini 429 Rate Limit` | API quota exhaustion | The `resilient_executor.py` engine automatically rotates across candidate models (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.6-flash`) and uses deterministic offline rule fallback to prevent user disruption. |

---

## License

This project is licensed under the Apache License 2.0.
