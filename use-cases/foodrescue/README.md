# FoodRescue AI — AI-Powered Surplus-Food Coordination Platform

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Agent Kernel](https://img.shields.io/badge/Agent%20Kernel-0.8.1-emerald.svg)](https://kernel.yaala.ai)
[![Google Gemini](https://img.shields.io/badge/LLM-Gemini-orange.svg)](https://deepmind.google/technologies/gemini/)
[![Vercel Deployment](https://img.shields.io/badge/Deployed-Vercel%20Production-black.svg)](https://foodrescue-ai-ten.vercel.app)
[![MongoDB Atlas](https://img.shields.io/badge/Database-MongoDB%20Atlas-green.svg)](https://www.mongodb.com/atlas)
[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

> **Live Production Application**: [https://foodrescue-ai-ten.vercel.app](https://foodrescue-ai-ten.vercel.app)  
> **Interactive OpenAPI Documentation**: [https://foodrescue-ai-ten.vercel.app/docs](https://foodrescue-ai-ten.vercel.app/docs)  
> **Health Check Endpoint**: [https://foodrescue-ai-ten.vercel.app/health](https://foodrescue-ai-ten.vercel.app/health)

---

## 🚨 1. Problem Statement

Every day, commercial kitchens, hotels, supermarkets, and event caterers discard millions of prepared, untouched, and nutritious meals simply because manual donation logistics are too slow and fragmented:
1. **Time-Critical Expiration**: Prepared meals spoil within narrow safety windows (2–4 hours) if not promptly matched and transported.
2. **Coordination Friction**: Food donors lack dedicated staff to manually call charities, verify dietary compatibility (vegetarian, halal), and find available drivers.
3. **Logistics Bottlenecks**: Recipient charities often lack vehicles and rely on ad-hoc volunteer couriers whose availability changes constantly.
4. **Context Loss in Communication**: Donors provide partial details across multiple messages, causing traditional static bots or rule engines to fail or ask redundant questions.

---

## 💡 2. Solution Overview

**FoodRescue AI** is an autonomous multi-agent surplus-food dispatch platform built with **Agent Kernel** and **Google ADK (Gemini)**. It automates the entire surplus food rescue lifecycle in seconds:

```text
┌───────────────────────────┐      ┌───────────────────────────┐      ┌───────────────────────────┐      ┌───────────────────────────┐
│  1. Donors Report Surplus │ ───▶ │   2. AI Matches Recipient │ ───▶ │  3. AI Assigns Volunteer  │ ───▶ │  4. Track 7-Stage Logistics│
│  Restaurants & hotels log │      │   Evaluates food type,    │      │   Dispatches nearby       │      │   Real-time progression   │
│  surplus via chat or form │      │   dietary rules & capacity│      │   courier based on mode   │      │   from pickup to delivery │
└───────────────────────────┘      └───────────────────────────┘      └───────────────────────────┘      └───────────────────────────┘
```

* **Natural-Language Ingestion**: Donors report surplus food in plain English (e.g. *"I am donor d1. I have 40 vegetarian lunch boxes in Colombo 3 ready until 7 PM"*).
* **Multi-Turn Context Preservation**: Built-in Agent Kernel session memory retains active donation IDs, quantities, and locations across turns without reprompting.
* **Autonomous Matching Engine**: Automatically ranks and matches recipient organizations based on geographic proximity, accepted food categories, and real-time shelter capacity.
* **Proximity Volunteer Assignment**: Automatically finds and assigns nearby couriers (bicycle, motorbike, van) and schedules pickup tasks.
* **7-Stage Lifecycle Tracking**: Complete real-time audit trail and state machine from donation availability to confirmed delivery.

---

## ⚙️ 3. Setup Instructions

### Prerequisites
* Python 3.12+
* [uv](https://docs.astral.sh/uv/) (recommended) or standard `pip` / `venv`
* Git

### Step 1: Clone Repository & Enter Directory
```bash
git clone https://github.com/mohommadhuafnan/agent-kernel.git
cd agent-kernel/use-cases/foodrescue
```

### Step 2: Create & Activate Virtual Environment
```bash
# Using uv (fast):
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv sync

# Or using standard python:
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
Create a local `.env` file in `use-cases/foodrescue/` (this file is gitignored):
```env
GEMINI_API_KEY="your-gemini-api-key"
GEMINI_MODEL="gemini-3.5-flash-lite"
FOODRESCUE_DB_BACKEND="sqlite"
FOODRESCUE_DB_PATH="foodrescue.db"
```

---

## 🚀 4. How to Run the Solution

### Start Local Server
```bash
python server.py
```
The server will start listening at **`http://localhost:8000`**:
* **Web UI Dashboard**: `http://localhost:8000/`
* **Interactive OpenAPI Documentation**: `http://localhost:8000/docs`
* **Agent Kernel Chat API**: `POST http://localhost:8000/api/v1/chat`
* **Health Check**: `GET http://localhost:8000/health`

---

## ⚡ 5. Why Agent Kernel?

FoodRescue AI solves a real-world multi-party logistics coordination challenge where traditional rule engines fail:
* **Decoupled Architecture**: Framework-agnostic core enables switching between LLM backends (Google ADK Gemini) and persistence backends (SQLite / MongoDB Atlas) with zero changes to business logic.
* **First-Class Session Memory**: Native `SessionStore` and `KeyValueCache` isolate working memory per conversation thread, preventing context bleeding between simultaneous donors.
* **Tool-Driven Execution**: 14 modular, typed tools encapsulate domain operations (validation, ranking, dispatching, state updates) cleanly without relying on brittle LLM prompt engineering.
* **Production-Ready Server Layer**: Built-in `RESTAPI` mounts FastAPI routes, enabling both human users (Web UI) and automated systems to communicate with the agent via standard REST contracts.

---

## 🏛️ 6. System Architecture

```text
                                  ┌───────────────────────────────────────────────┐
                                  │           FoodRescue Web UI (SPA)             │
                                  │      (7-Tab Modern Glassmorphic Dashboard)   │
                                  └──────────────────────┬────────────────────────┘
                                                         │
                                                         ▼
                                  ┌───────────────────────────────────────────────┐
                                  │        Agent Kernel REST API Server           │
                                  │   (/api/v1/chat, /api/stats, /api/donations)  │
                                  └──────────────────────┬────────────────────────┘
                                                         │
                                                         ▼
                                  ┌───────────────────────────────────────────────┐
                                  │   Resilient Execution Engine & Model Pool     │
                                  │   Gemini 3.5 Flash ──▶ 3.1 Flash ──▶ Flash L. │
                                  └──────────────────────┬────────────────────────┘
                                                         │
                                                         ▼
                                  ┌───────────────────────────────────────────────┐
                                  │       foodrescue_coordinator (Google ADK)     │
                                  └──────────────────────┬────────────────────────┘
                                                         │
                             ┌───────────────────────────┴───────────────────────────┐
                             ▼                                                       ▼
  ┌─────────────────────────────────────────────────────┐ ┌─────────────────────────────────────────────────────┐
  │         Agent Kernel Session Memory                 │ │          14 Bound Operational Tools                 │
  │     (KeyValueCache persistent context)              │ │  • create_donation        • assign_volunteer        │
  │  • current_donation_id  • current_food_type         │ │  • update_donation_details• update_pickup_status    │
  │  • current_location     • workflow_step             │ │  • find_matching_orgs     • get_session_context     │
  └─────────────────────────────────────────────────────┘ └──────────────────────────┬──────────────────────────┘
                                                                                     │
                                                                                     ▼
                                                          ┌─────────────────────────────────────────────────────┐
                                                          │     database.py (Repository Delegation Layer)       │
                                                          └──────────────────────────┬──────────────────────────┘
                                                                                     │
                                                         ┌───────────────────────────┴───────────────────────────┐
                                                         ▼                                                       ▼
                                      ┌─────────────────────────────────────┐ ┌─────────────────────────────────────┐
                                      │  SQLiteRepository (Local / Tests)   │ │   MongoRepository (Cloud / Atlas)   │
                                      │  foodrescue.db                      │ │   MONGODB_URI                       │
                                      └─────────────────────────────────────┘ └─────────────────────────────────────┘
```

---

## 🤖 7. Agent Definition

* **Agent Identifier**: `foodrescue_coordinator`
* **Framework Adapter**: `agentkernel.framework.adk.GoogleADKModule`
* **Role**: Autonomous surplus-food dispatcher responsible for validating donations, selecting matching recipient organizations, scheduling transport tasks, assigning volunteer couriers, and advancing lifecycle statuses.

---

## 🛠️ 8. The 14 Bound Operational Tools

Defined in [tools.py](file:///c:/Users/PC/agent-kernel/use-cases/foodrescue/tools.py):

| Tool Name | Category | Purpose |
| :--- | :--- | :--- |
| `create_donation` | Creation | Validates donor, food type, quantity (>0), location, and creates donation record. |
| `update_donation_details` | Mutation | Updates quantity, dietary tags, or deadlines for an active session donation. |
| `get_donation` | Inspection | Fetches complete donation details and status. |
| `update_donation_status` | State Machine | Transitions status across allowed enums (`AVAILABLE` → `MATCHED` → `DELIVERED`). |
| `find_matching_organizations` | Matching | Ranks food banks and shelters by dietary rules, capacity, and proximity. |
| `accept_donation` | Matching | Links donation to recipient organization and transitions status to `MATCHED`. |
| `find_available_volunteers` | Courier Dispatch | Searches and ranks active volunteers based on vehicle mode and proximity. |
| `create_pickup_task` | Logistics | Creates delivery task with pickup window and scheduled delivery time. |
| `get_pickup_task` | Logistics | Retrieves task status and assigned courier information. |
| `assign_volunteer` | Courier Dispatch | Binds courier to task and advances status to `PICKUP_ASSIGNED`. |
| `update_pickup_status` | Progression | Advances task through `EN_ROUTE` → `COLLECTED` → `DELIVERED`. |
| `get_session_context` | Memory | Returns active donor, donation ID, food details, and workflow step. |
| `set_session_context` | Memory | Explicitly sets preliminary working variables in session cache. |
| `clear_session_context` | Memory | Clears working memory to start a fresh donation workflow. |

---

## 🧠 9. Session Memory & Multi-Turn Continuity

Agent Kernel's `KeyValueCache` enables seamless multi-turn state preservation:
* **Turn 1 (Initial Report)**: Donor reports `"I am donor d1. I have 40 vegetarian lunch boxes in Colombo 3."` ➔ Creates donation `don-xxxx`, stores `current_donation_id = don-xxxx` in memory.
* **Turn 2 (Incremental Update)**: Donor adds `"They need to be collected before 7 PM."` ➔ Coordinator reads `current_donation_id` from working memory and updates the deadline without asking the user to repeat the food type or quantity.
* **Turn 3 (Autonomous Dispatch)**: Donor says `"Find a match and assign a volunteer."` ➔ Coordinator uses cached location and food details to match the charity and assign a courier.

---

## ⚡ 10. Gemini Multi-Model Intelligence & Resilient Pool

To guarantee uninterrupted operation during demonstrations, [resilient_executor.py](file:///c:/Users/PC/agent-kernel/use-cases/foodrescue/resilient_executor.py) implements automatic model rotation:
1. **Primary Model**: `gemini-3.5-flash-lite` (High throughput and fast response times)
2. **Secondary Failover**: `gemini-3.1-flash-lite`
3. **Tertiary Failover**: `gemini-3.6-flash`
4. **Deterministic Rule Engine Fallback**: If all upstream LLM quotas are exhausted, the system automatically executes the 14 tools deterministically so users never experience a failed request.

---

## 🗄️ 11. Dual-Backend Database Architecture

Inherits from [BaseRepository](file:///c:/Users/PC/agent-kernel/use-cases/foodrescue/db_base.py) via [database.py](file:///c:/Users/PC/agent-kernel/use-cases/foodrescue/database.py):
* **`SQLiteRepository`**: Local embedded SQLite database (`foodrescue.db`) for zero-dependency development and offline test execution.
* **`MongoRepository`**: High-availability cloud persistence using MongoDB Atlas with collections for `donations`, `organizations`, `volunteers`, `pickup_tasks`, and `notifications`.

---

## 🌐 12. REST API Endpoints

| Endpoint | Method | Access | Description |
| :--- | :--- | :--- | :--- |
| `/` & `/ui` | `GET` | Public | Single Page Web Application dashboard. |
| `/health` | `GET` | Public | Deployment health check and liveness probe. |
| `/api/stats` | `GET` | Public | Aggregated KPIs and 7-stage status distribution. |
| `/api/donations` | `GET` | Public | List all donations with optional `?status=` filter. |
| `/api/donations/{id}` | `GET` | Public | Single donation detail with linked donor, recipient, and pickup tasks. |
| `/api/organizations` | `GET` | Public | Verified recipient organizations directory. |
| `/api/volunteers` | `GET` | Public | Active volunteer couriers directory. |
| `/api/pickups` | `GET` | Public | Logistics pickup tasks list with assigned couriers. |
| `/api/notifications` | `GET` | Public | Transparency and audit log feed (capped at `limit <= 200`). |
| `/api/v1/agents` | `GET` | Public | Agent Kernel agent discovery endpoint. |
| `/api/v1/chat` | `POST` | Public (Validated) | Resilient multi-model conversational chat endpoint with automatic failover. |
| `/api/session-context/{session_id}` | `GET` | Public (Sanitized) | Diagnostic session state inspection (sensitive keys stripped). |
| `/api/reset-demo` | `POST` | **Protected (403)** | **Disabled in production.** Requires `X-Admin-Key` header matching `ADMIN_API_KEY`. |

---

## 🖥️ 13. Web UI Navigation Structure (7 Views)

1. 📊 **Dashboard**: 6 real-time KPI cards (Total Donations, Meals Rescued, Active Pickups, Matched Orgs, Available Volunteers, Completed Deliveries), 4-pillar hero explainer, 7-stage status pipeline bar, and live audit feed.
2. 🤖 **AI Assistant**: Natural-language coordinator chat powered by Gemini, interactive judge test prompt chips, 3-turn demo button, and live active session memory sidebar.
3. 📦 **Donations**: Interactive 7-stage visual lifecycle stepper with one-click progression actions, search bar, status filter pills, and complete donation registry.
4. 🏢 **Organizations**: Verified recipient organizations directory (capacity, accepted food types, location, masked phone contact).
5. 🚴 **Volunteers**: Registered courier roster with active availability (`available` vs `busy`), transport mode (Electric Bike, Motorbike, Van), and assigned pickups.
6. 🚚 **Pickups & Logistics**: Logistics task board with dynamic routing, road distance estimation, live opt-in GPS tracking, and travel reimbursement calculations.
7. ⚖️ **Reimbursements**: Volunteer travel reimbursement ledger tracking mileage estimates and administrative approval states (PENDING ➔ APPROVED ➔ PAID).
8. 🧠 **Session / Activity**: Agent Kernel session memory inspector displaying structured `KeyValueCache` variables, multi-turn architecture explainer, and live notification audit stream.

---

## 🗺️ 14. Phase 7: Advanced Logistics, Routing & Reimbursement

FoodRescue AI includes a production-ready civic logistics engine designed for non-profit surplus food redistribution:

### A. Automatic Transport Cost Estimation
* **Configurable Rates**: Rates are driven by environment configuration (`TRANSPORT_RATE_BICYCLE`, `TRANSPORT_RATE_MOTORBIKE`, `TRANSPORT_RATE_CAR`, `TRANSPORT_RATE_VAN`):
  * **Bicycle / Electric Bike**: 25 LKR / km
  * **Motorbike**: 50 LKR / km
  * **Car**: 80 LKR / km
  * **Van**: 120 LKR / km
* **Formula**: $\text{Estimated Cost} = \text{Distance (km)} \times \text{Rate per km}$

> [!IMPORTANT]
> **Non-Payment Accounting Ledger Notice**: This prototype records estimated volunteer travel reimbursement amounts as an internal civic accounting ledger. It **deliberately does not** process monetary payments, credit cards, wallets, or bank transfers.

### B. Dynamic Routing (Google Routes API + Haversine Fallback)
* **Google Routes API Integration**: When `ROUTING_API_KEY` is configured, calculates exact road distances (km), travel durations (minutes), and polyline route geometry via `https://routes.googleapis.com/directions/v2:computeRoutes`.
* **Zero-API Haversine Fallback**: If `ROUTING_API_KEY` is missing or the external network times out, seamlessly falls back to spherical Haversine distance with road-curvature correction ($1.25\times$).

### C. Live Opt-In GPS Tracking & Privacy
* **Strict Privacy Controls**: GPS tracking is **OFF by default**.
* **Opt-In Trigger**: Activated only when volunteer courier explicitly clicks *"Start Live GPS"* in the browser (`navigator.geolocation.watchPosition`).
* **Automatic Lifecycle Stops**: Location tracking automatically ceases the moment pickup status progresses to `COLLECTED` or `DELIVERED`.
* **Coordinate Validation**: Validates latitude ($-90^\circ \dots 90^\circ$) and longitude ($-180^\circ \dots 180^\circ$).

### D. Volunteer Reimbursement Ledger
* **State Machine**: `PENDING` ➔ `APPROVED` ➔ `PAID` (or `CANCELLED`).
* **Automatic Creation**: Triggered when a pickup task reaches `DELIVERED` status.
* **Dual Persistence Parity**: Implemented and indexed across SQLite (`reimbursements`, `pickup_location_history`) and MongoDB Atlas collections.

---

## 🌍 15. UN Sustainable Development Goals (SDG) Alignment

FoodRescue AI directly supports the United Nations 2030 Agenda for Sustainable Development:

* 🎯 **SDG 2: Zero Hunger (Target 2.1)**: Eliminates food insecurity by rapidly connecting edible surplus meals from commercial kitchens with verified community kitchens and shelters.
* ♻️ **SDG 12: Responsible Consumption & Production (Target 12.3)**: Directly targets halving per capita global food waste along production and supply chains.
* 🌿 **SDG 13: Climate Action**: Reduces organic food waste in municipal landfills, mitigating greenhouse gas (methane) emissions.
* 🤝 **SDG 17: Partnerships for the Goals**: Builds digital coordination bridges among private businesses (hotels/restaurants), non-profit charities, and civic volunteer couriers.

---

## 🧪 16. Testing Suite & Verification

### Test Results Summary
* **Offline Test Suite**: **61 passed, 2 skipped out of 63 tests** (100% pass rate in ~7.8s).
* **Live Google Routes API Test**: **1 passed** with real Routes API key.
* **Controlled Live Gemini Test**: **1 passed** (autonomous coordinator verified with Gemini).
* **Production Smoke Test Suite**: **18/18 checks passed** against live Vercel deployment.

### Running Tests Locally
```bash
# 1. Run Complete Offline Test Suite (63 tests)
pytest -v test_foodrescue.py test_foodrescue_mongodb.py test_foodrescue_whatsapp.py test_foodrescue_logistics.py

# 2. Run Live Google Routes API Test (Opt-In with Key)
ROUTING_API_KEY="your-api-key" pytest -v test_foodrescue_logistics.py -k "test_route_provider_live"

# 3. Run Controlled Live Gemini Integration Test
pytest -v test_foodrescue_gemini.py

# 4. Run Production Smoke Test Suite (18 Checks)
python verify_production.py
```

---

## ☁️ 17. Production Deployment

* **Hosting Platform**: Vercel Serverless ASGI (`vercel.json`)
* **Live Target**: [https://foodrescue-ai-ten.vercel.app](https://foodrescue-ai-ten.vercel.app)
* **Database Backend**: MongoDB Atlas (`MONGODB_URI`, `MONGODB_DATABASE`)
* **Security Hardening**:
  * Zero hardcoded secrets in source files or client bundles.
  * Production credentials reside exclusively in Vercel environment variables.
  * `/api/reset-demo` returns `403 Forbidden` in production without authorized admin key.
  * `/api/session-context/{session_id}` automatically sanitizes internal memory fields.
  * CORS restricted to production domains and localhost development ports.

---

## 🏆 17. Judge Demonstration Walkthrough (5-Minute Script)

1. **Open Application**: Navigate to **[https://foodrescue-ai-ten.vercel.app](https://foodrescue-ai-ten.vercel.app)**.
2. **Execute Automated Demo**: Click **`▶ Run 3-Turn Demo`** in the top bar.
   * **Turn 1**: Submits: `"I am donor d1. I have 40 vegetarian lunch boxes in Colombo 3."` ➔ Donation `don-xxxx` created and stored in session cache.
   * **Turn 2**: Submits: `"They need to be collected before 7 PM."` ➔ Deadline updated without re-asking any info.
   * **Turn 3**: Submits: `"Find a matching organization, schedule pickup, and assign an available volunteer."` ➔ Recipient matched, pickup task created, courier assigned.
3. **Inspect Session Memory**: View the **Active Session Memory** card in the AI Assistant sidebar showing all live `KeyValueCache` variables.
4. **Track Lifecycle**: Click **Donations** tab, select the donation, and use **`🚗 Mark En Route`** ➔ **`📦 Mark Collected`** ➔ **`✅ Confirm Delivered`** to progress the 7-stage visual stepper.
5. **Verify Logistics & Audit Trail**: Check the **Pickups** board and the **Session / Activity** audit feed.

---

## 📋 18. Known Limitations & Channel Status

* **Official Supported Client**: Interactive Web Application and OpenAPI REST API (`/api/v1/chat`).
* **WhatsApp Integration Status**: WhatsApp Cloud API adapter implemented and unit-tested; live Meta webhook dispatch is not part of the competition demo deployment. The adapter code (`whatsapp_handler.py`) and test suite (`test_foodrescue_whatsapp.py`, 10 tests) are verified for developers wishing to connect their own Meta Business app.
* **Volunteer Matching Scope**: When all registered volunteers in a geographic area are busy or unavailable, the system transparently logs the unassigned task and notifies the donor/organization without creating false assignments.
