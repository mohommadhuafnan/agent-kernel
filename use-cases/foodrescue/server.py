"""FoodRescue AI REST API & WhatsApp Server Entrypoint.

Starts the Agent Kernel built-in REST API server hosting:
1. Native Agent Kernel chat & agents API (/api/v1/chat, /api/v1/agents)
2. FoodRescue Single Page Web UI & custom dashboard endpoints
3. Meta WhatsApp Business Cloud API webhook (/whatsapp/webhook)
"""

import logging
import app  # Loads foodrescue_coordinator and registers GoogleADKModule
import api_routes
import whatsapp_handler
from agentkernel.api import RESTAPI

logger = logging.getLogger("foodrescue.server")

# Register custom Web API and UI router
RESTAPI.add(api_routes.get_router())

# Register Meta WhatsApp Cloud API webhook router
RESTAPI.add(whatsapp_handler.get_whatsapp_router())

if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("  🍲 FoodRescue AI — Unified REST API & WhatsApp Server")
    print("=" * 65)
    print("  • Host:                0.0.0.0 (http://localhost:8000)")
    print("  • Web UI:              http://localhost:8000/")
    print("  • REST API Chat:       POST http://localhost:8000/api/v1/chat")
    print("  • WhatsApp Webhook:    POST http://localhost:8000/whatsapp/webhook")
    print("  • Webhook Verify URL:  GET  http://localhost:8000/whatsapp/webhook")
    print("  • WhatsApp Status:     GET  http://localhost:8000/api/whatsapp/status")
    print("  • Registered Number:   +94 75 526 3482")
    print(f"  • Phone Number ID:     {whatsapp_handler.get_phone_number_id()}")
    print(f"  • WABA ID:             {whatsapp_handler.get_waba_id()}")
    print(f"  • Meta App ID:         {whatsapp_handler.get_app_id()}")
    print(f"  • Business ID:         {whatsapp_handler.get_business_id()}")
    print("=" * 65 + "\n")
    RESTAPI.run()
