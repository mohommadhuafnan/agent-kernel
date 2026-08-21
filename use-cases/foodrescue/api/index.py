"""Vercel Serverless Entrypoint for FoodRescue AI.

Exposes the ASGI FastAPI application instance `app` with hardened CORS,
production route isolation, and single canonical agent registration.
"""

import os
import sys
from fastapi.middleware.cors import CORSMiddleware

# Ensure project root directory is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Configure safe serverless storage path on Vercel (/tmp is the only writable directory)
if (os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")) and not os.environ.get("FOODRESCUE_DB_PATH"):
    os.environ["FOODRESCUE_DB_PATH"] = "/tmp/foodrescue.db"

import app as ak_app  # Loads foodrescue_coordinator and registers GoogleADKModule
import api_routes
import whatsapp_handler
import database
from agentkernel.api import RESTAPI, AgentRESTRequestHandler

# Initialize active database backend (SQLite / MongoDB Atlas) on cold start
try:
    database.setup_database()
    database.seed_test_data()
except Exception as init_err:
    print(f"[Vercel Init] Database setup notice: {init_err}")

# Allowed origins: Deployed Vercel frontend + local development
ALLOWED_ORIGINS_RAW = os.environ.get(
    "ALLOWED_ORIGINS",
    "https://foodrescue-ai-ten.vercel.app,https://foodrescue-ai.vercel.app,http://localhost:8000,http://localhost:3000,http://127.0.0.1:8000,http://127.0.0.1:3000"
)
ALLOWED_ORIGINS = [o.strip() for o in ALLOWED_ORIGINS_RAW.split(",") if o.strip()]

# Assemble the ASGI FastAPI application
handler = AgentRESTRequestHandler()
app = RESTAPI._create_app(routers=[
    api_routes.get_router(),
    whatsapp_handler.get_whatsapp_router(),
    handler.get_router(),
])

# Apply explicit CORS security middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)
