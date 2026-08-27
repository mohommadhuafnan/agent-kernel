"""FoodRescue AI Supabase PostgreSQL Repository Implementation.

Encapsulates all PostgreSQL/Supabase storage operations, table setups, indexing,
transactional CRUD operations, proximity/dietary ranking algorithms, dynamic GPS routing,
and atomic physical QR handover verification.
"""

import os
import datetime
import json
import uuid
import logging
from typing import List, Dict, Any, Optional, Union
from db_base import BaseRepository

logger = logging.getLogger("foodrescue.db.supabase")


class SupabaseRepository(BaseRepository):
    """PostgreSQL / Supabase implementation of the FoodRescue persistence repository."""

    def __init__(
        self,
        db_url: Optional[str] = None,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
        connection_instance: Optional[Any] = None
    ):
        self._db_url = (
            db_url
            or os.environ.get("SUPABASE_DB_URL")
            or os.environ.get("DATABASE_URL")
            or os.environ.get("POSTGRES_URL")
            or ""
        )
        self._supabase_url = supabase_url or os.environ.get("SUPABASE_URL", "")
        self._supabase_key = (
            supabase_key
            or os.environ.get("SUPABASE_SECRET_KEY")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or os.environ.get("SUPABASE_KEY")
            or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
            or ""
        )
        self._connection: Optional[Any] = connection_instance
        self._engine: Optional[Any] = None
        self._supabase_client: Optional[Any] = None

    def get_supabase_client(self) -> Optional[Any]:
        """Return initialized supabase.Client SDK instance if URL and Key are configured."""
        if self._supabase_client is not None:
            return self._supabase_client
        if not self._supabase_url or not self._supabase_key:
            return None
        try:
            from supabase import create_client
            self._supabase_client = create_client(self._supabase_url, self._supabase_key)
            return self._supabase_client
        except Exception as e:
            logger.warning(f"Could not create Supabase Client instance: {e}")
            return None

    def _get_connection(self):
        """Retrieve or create an active database connection."""
        if self._connection is not None:
            return self._connection

        if not self._db_url:
            raise ValueError(
                "SUPABASE_DB_URL or DATABASE_URL environment variable is not configured. "
                "Set SUPABASE_DB_URL to connect to Supabase PostgreSQL, or use FOODRESCUE_DATABASE=sqlite."
            )

        # Normalize connection URL
        clean_url = self._db_url
        if clean_url.startswith("postgresql+psycopg2://") or clean_url.startswith("postgresql+psycopg://"):
            clean_url = "postgresql://" + clean_url.split("://", 1)[1]
        elif clean_url.startswith("postgres://"):
            clean_url = "postgresql://" + clean_url.split("://", 1)[1]

        # Try psycopg (v3)
        try:
            import psycopg
            conn = psycopg.connect(clean_url, autocommit=True, prepare_threshold=None)
            self._connection = conn
            return self._connection
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"psycopg (v3) connection attempt failed: {e}")

        # Try psycopg2
        try:
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(clean_url)
            conn.autocommit = True
            self._connection = conn
            return self._connection
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"psycopg2 connection attempt failed: {e}")

        # Try pg8000
        try:
            import pg8000.native
            import urllib.parse
            parsed = urllib.parse.urlparse(clean_url)
            conn = pg8000.native.Connection(
                user=parsed.username or "postgres",
                password=parsed.password or "",
                host=parsed.hostname or "localhost",
                port=parsed.port or 5432,
                database=parsed.path.lstrip("/") or "postgres",
                ssl_context=True if ("supabase.co" in (parsed.hostname or "") or parsed.port == 5432 or parsed.port == 6543) else None
            )
            self._connection = conn
            return self._connection
        except Exception as e:
            logger.warning(f"pg8000 connection attempt failed: {e}")

        # Try SQLAlchemy engine
        try:
            from sqlalchemy import create_engine
            engine = create_engine(self._db_url, pool_pre_ping=True)
            self._engine = engine
            return engine.connect()
        except Exception as e:
            raise ConnectionError(f"Could not connect to Supabase PostgreSQL: {e}")

    def _now(self) -> str:
        """Current ISO 8601 UTC timestamp."""
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def _normalize_phone(self, phone: Optional[str]) -> str:
        """Normalize phone number to digits only."""
        if not phone:
            return ""
        return "".join(ch for ch in str(phone) if ch.isdigit())

    def _json_dumps(self, val: Any) -> Optional[str]:
        if val is None:
            return None
        if isinstance(val, (dict, list)):
            return json.dumps(val)
        return str(val)

    def _json_loads(self, val: Any) -> Any:
        if val is None:
            return {}
        if isinstance(val, (dict, list)):
            return val
        if isinstance(val, str):
            val_strip = val.strip()
            if not val_strip or val_strip == "None":
                return {}
            try:
                return json.loads(val_strip)
            except Exception:
                return val
        return val

    def _adapt_query_for_sqlite(self, query: str) -> str:
        """Translate PostgreSQL query syntax to SQLite for test fixtures."""
        q = query.replace("%s", "?")
        q = q.replace("DEFAULT NOW()", "DEFAULT CURRENT_TIMESTAMP")
        q = q.replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP")
        q = q.replace("NOW()", "CURRENT_TIMESTAMP")
        q = q.replace("now()", "CURRENT_TIMESTAMP")
        q = q.replace("TIMESTAMPTZ", "TEXT")
        q = q.replace("JSONB", "TEXT")
        q = q.replace("::jsonb", "")
        q = q.replace("ILIKE", "LIKE")
        q = q.replace("BOOLEAN DEFAULT FALSE", "INTEGER DEFAULT 0")
        q = q.replace("BOOLEAN DEFAULT TRUE", "INTEGER DEFAULT 1")
        return q

    def _is_sqlite(self, conn: Any) -> bool:
        """Check if connection is an in-memory or local SQLite test connection."""
        return type(conn).__module__.startswith("sqlite3")

    def _execute(self, query: str, params: Optional[Union[tuple, list, dict]] = None) -> Any:
        """Execute a SQL query, adapting to the underlying connection dialect with auto-reconnect."""
        params = params or ()
        for attempt in range(2):
            try:
                conn = self._get_connection()

                # If it's a sqlite connection (used in test isolation)
                if self._is_sqlite(conn):
                    sqlite_query = self._adapt_query_for_sqlite(query)
                    cursor = conn.cursor()
                    cursor.execute(sqlite_query, params)
                    if not getattr(conn, "autocommit", False):
                        try:
                            conn.commit()
                        except Exception:
                            pass
                    return cursor

                # If it's pg8000.native.Connection
                if hasattr(conn, "run"):
                    return conn.run(query, *(params if isinstance(params, (tuple, list)) else (params,)))

                # Standard DB-API connection (psycopg / psycopg2 / standard)
                cursor = conn.cursor()
                cursor.execute(query, params)
                return cursor
            except Exception as err:
                if attempt == 0 and not self._is_sqlite(getattr(self, "_connection", None)):
                    logger.warning(f"SQL execute failed ({err}); attempting auto-reconnection...")
                    self._connection = None
                    continue
                raise

    def _fetchall(self, query: str, params: Optional[Union[tuple, list, dict]] = None) -> List[Dict[str, Any]]:
        """Execute query and return list of dictionaries with auto-reconnect."""
        params = params or ()
        for attempt in range(2):
            try:
                conn = self._get_connection()

                # SQLite connection
                if self._is_sqlite(conn):
                    sqlite_query = self._adapt_query_for_sqlite(query)
                    cursor = conn.cursor()
                    cursor.execute(sqlite_query, params)
                    columns = [col[0] for col in cursor.description] if cursor.description else []
                    rows = cursor.fetchall()
                    result = []
                    for row in rows:
                        if isinstance(row, dict):
                            result.append(dict(row))
                        else:
                            result.append(dict(zip(columns, row)))
                    return result

                # pg8000.native.Connection
                if hasattr(conn, "run"):
                    rows = conn.run(query, *(params if isinstance(params, (tuple, list)) else (params,)))
                    columns = [c["name"] for c in conn.columns] if hasattr(conn, "columns") else []
                    return [dict(zip(columns, r)) for r in rows]

                # psycopg / psycopg2
                cursor = conn.cursor()
                cursor.execute(query, params)
                columns = [col[0] for col in cursor.description] if cursor.description else []
                rows = cursor.fetchall()
                result = []
                for row in rows:
                    if isinstance(row, dict):
                        result.append(dict(row))
                    elif isinstance(row, (tuple, list)):
                        result.append(dict(zip(columns, row)))
                    else:
                        try:
                            result.append(dict(zip(columns, row)))
                        except Exception:
                            result.append(row)
                return result
            except Exception as err:
                if attempt == 0 and not self._is_sqlite(getattr(self, "_connection", None)):
                    logger.warning(f"SQL fetchall failed ({err}); attempting auto-reconnection...")
                    self._connection = None
                    continue
                raise

    def _fetchone(self, query: str, params: Optional[Union[tuple, list, dict]] = None) -> Optional[Dict[str, Any]]:
        """Execute query and return single dictionary or None."""
        rows = self._fetchall(query, params)
        return rows[0] if rows else None

    # --- Setup & Seeding ---

    def setup_database(self) -> None:
        """Create PostgreSQL tables and indexes if they do not exist."""
        # 1. Donors
        self._execute('''
        CREATE TABLE IF NOT EXISTS donors (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            phone VARCHAR(64),
            organization_name VARCHAR(255),
            location TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        ''')

        # 2. Organizations
        self._execute('''
        CREATE TABLE IF NOT EXISTS organizations (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            phone VARCHAR(64),
            service_area TEXT NOT NULL,
            accepted_food_types TEXT NOT NULL,
            capacity VARCHAR(128),
            availability VARCHAR(128) DEFAULT 'daytime',
            location TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        ''')

        # 3. Volunteers
        self._execute('''
        CREATE TABLE IF NOT EXISTS volunteers (
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
            current_coordinates TEXT,
            vehicle_capacity INTEGER DEFAULT 25,
            completed_pickups INTEGER DEFAULT 0,
            last_available_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        ''')

        # 4. Donations
        self._execute('''
        CREATE TABLE IF NOT EXISTS donations (
            id VARCHAR(64) PRIMARY KEY,
            donor_id VARCHAR(64) NOT NULL,
            food_type VARCHAR(255) NOT NULL,
            quantity NUMERIC(10, 2) NOT NULL,
            unit VARCHAR(64) NOT NULL,
            dietary_information TEXT,
            pickup_location TEXT NOT NULL,
            available_from VARCHAR(128) NOT NULL,
            pickup_deadline VARCHAR(128) NOT NULL,
            status VARCHAR(64) NOT NULL DEFAULT 'AVAILABLE',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        ''')

        # 5. Pickup Tasks
        self._execute('''
        CREATE TABLE IF NOT EXISTS pickup_tasks (
            id VARCHAR(64) PRIMARY KEY,
            donation_id VARCHAR(64) NOT NULL,
            organization_id VARCHAR(64) NOT NULL,
            volunteer_id VARCHAR(64),
            pickup_location TEXT NOT NULL,
            pickup_coordinates TEXT,
            pickup_location_confirmed BOOLEAN DEFAULT FALSE,
            delivery_location TEXT NOT NULL,
            destination_coordinates TEXT,
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
        )
        ''')

        # 6. Notifications
        self._execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id VARCHAR(64) PRIMARY KEY,
            recipient_type VARCHAR(64) NOT NULL,
            recipient_id VARCHAR(64) NOT NULL,
            message TEXT NOT NULL,
            channel VARCHAR(64) NOT NULL,
            status VARCHAR(64) NOT NULL DEFAULT 'SENT',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        ''')

        # 7. Audit Events
        self._execute('''
        CREATE TABLE IF NOT EXISTS audit_events (
            id VARCHAR(64) PRIMARY KEY,
            event_type VARCHAR(128) NOT NULL,
            actor VARCHAR(128) NOT NULL,
            related_id VARCHAR(64),
            metadata TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        ''')

        # 8. Reimbursements
        self._execute('''
        CREATE TABLE IF NOT EXISTS reimbursements (
            id VARCHAR(64) PRIMARY KEY,
            pickup_task_id VARCHAR(64) NOT NULL,
            volunteer_id VARCHAR(64) NOT NULL,
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
        )
        ''')

        # 9. Pickup Location History
        self._execute('''
        CREATE TABLE IF NOT EXISTS pickup_location_history (
            id VARCHAR(64) PRIMARY KEY,
            pickup_task_id VARCHAR(64) NOT NULL,
            volunteer_id VARCHAR(64) NOT NULL,
            latitude NUMERIC(10, 7) NOT NULL,
            longitude NUMERIC(10, 7) NOT NULL,
            accuracy_m NUMERIC(10, 2),
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        ''')

        # 10. Users
        self._execute('''
        CREATE TABLE IF NOT EXISTS users (
            phone_number VARCHAR(64) PRIMARY KEY,
            display_name VARCHAR(255),
            preferred_language VARCHAR(32) DEFAULT 'en',
            preferred_response_mode VARCHAR(32) DEFAULT 'text',
            user_role VARCHAR(64) DEFAULT 'unknown',
            default_location TEXT,
            active_donation_id VARCHAR(64),
            active_task_id VARCHAR(64),
            conversation_state TEXT,
            active_draft TEXT,
            onboarding_completed BOOLEAN DEFAULT FALSE,
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            metadata TEXT
        )
        ''')

        # 11. Messages
        self._execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id VARCHAR(64) PRIMARY KEY,
            phone_number VARCHAR(64) NOT NULL,
            sender VARCHAR(64) NOT NULL,
            message_text TEXT NOT NULL,
            is_voice BOOLEAN DEFAULT FALSE,
            transcript TEXT,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        ''')

        # 12. System Settings
        self._execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            setting_key VARCHAR(128) PRIMARY KEY,
            setting_value TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        ''')

        # 13. QR Codes
        self._execute('''
        CREATE TABLE IF NOT EXISTS qr_codes (
            id VARCHAR(64) PRIMARY KEY,
            task_id VARCHAR(64) NOT NULL,
            donation_id VARCHAR(64) NOT NULL,
            qr_type VARCHAR(32) NOT NULL,
            token VARCHAR(255) UNIQUE NOT NULL,
            token_hash VARCHAR(255),
            donor_id VARCHAR(64),
            organization_id VARCHAR(64),
            assigned_volunteer_id VARCHAR(64),
            status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ,
            verified_at TIMESTAMPTZ,
            verified_by VARCHAR(128),
            metadata TEXT
        )
        ''')

        # Seed default system settings
        default_cost = {
            "base_fare": 100.0,
            "cost_per_km": 80.0,
            "currency": "LKR",
            "rates_by_vehicle": {
                "Motorbike": 50.0,
                "Three-Wheeler": 90.0,
                "Car": 80.0,
                "Van": 120.0,
                "Bicycle": 25.0,
                "Electric Bike": 25.0
            },
            "vehicle_multipliers": {
                "Motorbike": 1.0,
                "Bicycle": 0.6,
                "Car": 1.5,
                "Van": 2.0,
                "Three-Wheeler": 1.2
            }
        }
        existing_setting = self._fetchone("SELECT setting_key FROM system_settings WHERE setting_key = %s", ("transport_cost",))
        if not existing_setting:
            self._execute(
                "INSERT INTO system_settings (setting_key, setting_value, updated_at) VALUES (%s, %s, %s)",
                ("transport_cost", json.dumps(default_cost), self._now())
            )

    def seed_test_data(self) -> None:
        """Seed master test data if tables are empty."""
        now = self._now()
        donors_count = len(self._fetchall("SELECT id FROM donors"))
        if donors_count == 0:
            self._execute(
                "INSERT INTO donors (id, name, phone, organization_name, location, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                ("d1", "Grand Hotel", "+94112345678", "Grand Hotel Colombo", "Colombo", now)
            )
            self._execute(
                "INSERT INTO donors (id, name, phone, organization_name, location, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                ("d2", "City Bakery", "+94112345679", "City Bakery Colombo", "Colombo 4", now)
            )

        orgs_count = len(self._fetchall("SELECT id FROM organizations"))
        if orgs_count == 0:
            self._execute(
                "INSERT INTO organizations (id, name, phone, service_area, accepted_food_types, capacity, availability, location, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                ("o1", "Community Kitchen Colombo", "+94119876543", "Colombo, Dehiwala", "vegetarian, non-vegetarian, lunch packets, cooked meals, bakery items", "200 meals", "always", "Colombo 7", now)
            )
            self._execute(
                "INSERT INTO organizations (id, name, phone, service_area, accepted_food_types, capacity, availability, location, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                ("o2", "Hope Food Bank", "+94119876544", "Colombo 3, Colombo 4, Wellawatte", "dry rations, bakery items, vegetarian", "100 meals", "daytime", "Colombo 4", now)
            )

        vols_count = len(self._fetchall("SELECT id FROM volunteers"))
        if vols_count == 0:
            self._execute(
                "INSERT INTO volunteers (id, name, phone, service_area, transport_mode, availability, current_status, availability_status, location, vehicle_capacity, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                ("v1", "Amara Silva", "+94771234567", "Colombo, Colombo 3, Colombo 4, Colombo 7", "Motorbike", "immediate, evenings", "available", "AVAILABLE", "Colombo 3", 25, now)
            )
            self._execute(
                "INSERT INTO volunteers (id, name, phone, service_area, transport_mode, availability, current_status, availability_status, location, vehicle_capacity, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                ("v2", "Kamal Perera", "+94771234568", "Colombo, Dehiwala, Mount Lavinia", "Three-Wheeler", "weekends, evenings", "available", "AVAILABLE", "Colombo 5", 40, now)
            )

    # --- Donors ---

    def get_donor_record(self, donor_id: str) -> Optional[Dict[str, Any]]:
        row = self._fetchone("SELECT * FROM donors WHERE id = %s", (donor_id,))
        return row

    def get_donor_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        if not phone:
            return None
        norm_digits = self._normalize_phone(phone)
        rows = self._fetchall("SELECT * FROM donors")
        for d in rows:
            d_digits = self._normalize_phone(d.get("phone", ""))
            if d_digits and norm_digits and (d_digits == norm_digits or (len(d_digits) >= 9 and len(norm_digits) >= 9 and d_digits[-9:] == norm_digits[-9:])):
                return d
        return None

    def create_donor_record(
        self,
        donor_id: str,
        name: str,
        phone: str,
        location: str,
        organization_name: Optional[str] = None
    ) -> Dict[str, Any]:
        now = self._now()
        org_name = organization_name or name
        self._execute(
            "INSERT INTO donors (id, name, phone, organization_name, location, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (donor_id, name, phone, org_name, location, now)
        )
        return self.get_donor_record(donor_id) or {
            "id": donor_id, "name": name, "phone": phone, "organization_name": org_name, "location": location, "created_at": now
        }

    # --- Organizations ---

    def get_organization_record(self, org_id: str) -> Optional[Dict[str, Any]]:
        return self._fetchone("SELECT * FROM organizations WHERE id = %s", (org_id,))

    def get_organization_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        if not phone:
            return None
        norm_digits = self._normalize_phone(phone)
        rows = self._fetchall("SELECT * FROM organizations")
        for o in rows:
            o_digits = self._normalize_phone(o.get("phone", ""))
            if o_digits and norm_digits and (o_digits == norm_digits or (len(o_digits) >= 9 and len(norm_digits) >= 9 and o_digits[-9:] == norm_digits[-9:])):
                return o
        return None

    def create_organization_record(
        self,
        org_id: str,
        name: str,
        phone: str,
        service_area: str,
        accepted_food_types: str,
        capacity: Optional[str] = None,
        availability: Optional[str] = "daytime",
        location: Optional[str] = None
    ) -> Dict[str, Any]:
        now = self._now()
        loc = location or service_area.split(",")[0].strip()
        cap = capacity if (capacity and str(capacity).strip()) else "As needed"
        avail = availability or "daytime"
        self._execute(
            "INSERT INTO organizations (id, name, phone, service_area, accepted_food_types, capacity, availability, location, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (org_id, name, phone, service_area, accepted_food_types, cap, avail, loc, now)
        )
        return self.get_organization_record(org_id) or {
            "id": org_id, "name": name, "phone": phone, "service_area": service_area,
            "accepted_food_types": accepted_food_types, "capacity": cap, "availability": avail,
            "location": loc, "created_at": now
        }

    def update_organization_record(
        self,
        org_id: str,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        service_area: Optional[str] = None,
        accepted_food_types: Optional[str] = None,
        capacity: Optional[str] = None,
        availability: Optional[str] = None,
        location: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        fields = []
        params = []
        if name is not None:
            fields.append("name = %s")
            params.append(name)
        if phone is not None:
            fields.append("phone = %s")
            params.append(phone)
        if service_area is not None:
            fields.append("service_area = %s")
            params.append(service_area)
        if accepted_food_types is not None:
            fields.append("accepted_food_types = %s")
            params.append(accepted_food_types)
        if capacity is not None:
            fields.append("capacity = %s")
            params.append(capacity)
        if availability is not None:
            fields.append("availability = %s")
            params.append(availability)
        if location is not None:
            fields.append("location = %s")
            params.append(location)

        if fields:
            params.append(org_id)
            self._execute(f"UPDATE organizations SET {', '.join(fields)} WHERE id = %s", tuple(params))
        return self.get_organization_record(org_id)

    # --- Volunteers ---

    def get_volunteer_record(self, volunteer_id: str) -> Optional[Dict[str, Any]]:
        row = self._fetchone("SELECT * FROM volunteers WHERE id = %s", (volunteer_id,))
        if row and row.get("current_coordinates"):
            row["current_coordinates"] = self._json_loads(row["current_coordinates"])
        return row

    def get_volunteer_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        if not phone:
            return None
        norm_digits = self._normalize_phone(phone)
        rows = self._fetchall("SELECT * FROM volunteers")
        for v in rows:
            v_digits = self._normalize_phone(v.get("phone", ""))
            if v_digits and norm_digits and (v_digits == norm_digits or (len(v_digits) >= 9 and len(norm_digits) >= 9 and v_digits[-9:] == norm_digits[-9:])):
                if v.get("current_coordinates"):
                    v["current_coordinates"] = self._json_loads(v["current_coordinates"])
                return v
        return None

    def create_volunteer_record(
        self,
        volunteer_id: str,
        name: str,
        phone: str,
        service_area: str,
        transport_mode: Optional[str] = "Motorbike",
        availability: Optional[str] = "available",
        current_status: Optional[str] = "available",
        location: Optional[str] = None
    ) -> Dict[str, Any]:
        now = self._now()
        mode = transport_mode or "Motorbike"
        loc = location or service_area.split(",")[0].strip()
        self._execute(
            "INSERT INTO volunteers (id, name, phone, service_area, transport_mode, availability_status, current_status, location, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (volunteer_id, name, phone, service_area, mode, availability or "available", current_status or "available", loc, now)
        )
        return self.get_volunteer_record(volunteer_id) or {
            "id": volunteer_id, "name": name, "phone": phone, "service_area": service_area,
            "transport_mode": mode, "availability_status": availability, "current_status": current_status,
            "location": loc, "created_at": now
        }

    def update_volunteer_record(
        self,
        volunteer_id: str,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        service_area: Optional[str] = None,
        transport_mode: Optional[str] = None,
        availability: Optional[str] = None,
        current_status: Optional[str] = None,
        location: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        fields = []
        params = []
        if name is not None:
            fields.append("name = %s")
            params.append(name)
        if phone is not None:
            fields.append("phone = %s")
            params.append(phone)
        if service_area is not None:
            fields.append("service_area = %s")
            params.append(service_area)
        if transport_mode is not None:
            fields.append("transport_mode = %s")
            params.append(transport_mode)
        if availability is not None:
            fields.append("availability_status = %s")
            params.append(availability)
        if current_status is not None:
            fields.append("current_status = %s")
            params.append(current_status)
        if location is not None:
            fields.append("location = %s")
            params.append(location)

        if fields:
            params.append(volunteer_id)
            self._execute(f"UPDATE volunteers SET {', '.join(fields)} WHERE id = %s", tuple(params))
        return self.get_volunteer_record(volunteer_id)

    # --- Donations ---

    def create_donation_record(
        self,
        donation_id: str,
        donor_id: str,
        food_type: str,
        quantity: float,
        unit: str,
        dietary_info: str,
        location: str,
        available_from: str,
        deadline: str
    ) -> Dict[str, Any]:
        qty = float(quantity)
        if qty <= 0:
            raise ValueError("Quantity must be greater than 0")

        now = self._now()
        self._execute(
            "INSERT INTO donations (id, donor_id, food_type, quantity, unit, dietary_information, pickup_location, available_from, pickup_deadline, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (donation_id, donor_id, food_type, qty, unit, dietary_info, location, available_from, deadline, "AVAILABLE", now, now)
        )
        return self.get_donation_record(donation_id) or {
            "id": donation_id, "donor_id": donor_id, "food_type": food_type, "quantity": qty,
            "unit": unit, "dietary_information": dietary_info, "pickup_location": location,
            "available_from": available_from, "pickup_deadline": deadline, "status": "AVAILABLE",
            "created_at": now, "updated_at": now
        }

    def get_donation_record(self, donation_id: str) -> Optional[Dict[str, Any]]:
        row = self._fetchone("SELECT * FROM donations WHERE id = %s", (donation_id,))
        if row and "quantity" in row:
            row["quantity"] = float(row["quantity"])
        return row

    def update_donation_status_record(self, donation_id: str, status: str) -> bool:
        now = self._now()
        self._execute(
            "UPDATE donations SET status = %s, updated_at = %s WHERE id = %s",
            (status, now, donation_id)
        )
        don = self.get_donation_record(donation_id)
        return don is not None and don.get("status") == status

    def update_donation_details_record(
        self,
        donation_id: str,
        food_type: Optional[str] = None,
        quantity: Optional[float] = None,
        unit: Optional[str] = None,
        dietary_info: Optional[str] = None,
        location: Optional[str] = None,
        available_from: Optional[str] = None,
        deadline: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        now = self._now()
        fields = ["updated_at = %s"]
        params = [now]

        if food_type is not None and str(food_type).strip():
            fields.append("food_type = %s")
            params.append(str(food_type).strip())
        if quantity is not None:
            fields.append("quantity = %s")
            params.append(float(quantity))
        if unit is not None and str(unit).strip():
            fields.append("unit = %s")
            params.append(str(unit).strip())
        if dietary_info is not None:
            fields.append("dietary_information = %s")
            params.append(str(dietary_info).strip())
        if location is not None and str(location).strip():
            fields.append("pickup_location = %s")
            params.append(str(location).strip())
        if available_from is not None and str(available_from).strip():
            fields.append("available_from = %s")
            params.append(str(available_from).strip())
        if deadline is not None and str(deadline).strip():
            fields.append("pickup_deadline = %s")
            params.append(str(deadline).strip())

        params.append(donation_id)
        self._execute(f"UPDATE donations SET {', '.join(fields)} WHERE id = %s", tuple(params))
        return self.get_donation_record(donation_id)

    def find_organizations_by_criteria(self, food_type: str, location: str) -> List[Dict[str, Any]]:
        loc_clean = location.strip().lower()
        food_clean = food_type.strip().lower()
        all_orgs = self._fetchall("SELECT * FROM organizations")

        import routing
        target_district = (routing.resolve_district(location) or "").lower()

        ranked_orgs = []
        for org in all_orgs:
            score = 0
            service_area = (org.get("service_area") or "").lower()
            org_location = (org.get("location") or "").lower()
            org_district = (routing.resolve_district(org.get("service_area") or org.get("location")) or "").lower()
            accepted_types = (org.get("accepted_food_types") or "").lower()

            if target_district and org_district and target_district == org_district:
                score += 30

            if loc_clean in service_area or loc_clean in org_location:
                score += 15
            elif any(part.strip() in service_area for part in loc_clean.split() if len(part.strip()) > 2):
                score += 5

            if food_clean in accepted_types:
                score += 10
            elif any(part.strip() in accepted_types for part in food_clean.split() if len(part.strip()) > 3):
                score += 5

            if score > 0:
                org["match_score"] = score
                ranked_orgs.append(org)

        ranked_orgs.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        return ranked_orgs if ranked_orgs else all_orgs

    def accept_donation_record(self, donation_id: str, organization_id: str) -> bool:
        don = self.get_donation_record(donation_id)
        if not don:
            return False
        now = self._now()
        self._execute(
            "UPDATE donations SET status = 'MATCHED', updated_at = %s WHERE id = %s",
            (now, donation_id)
        )
        return True

    def find_volunteers_by_criteria(self, location: str) -> List[Dict[str, Any]]:
        loc_clean = location.strip().lower()
        all_vols = self._fetchall("SELECT * FROM volunteers WHERE LOWER(current_status) = 'available'")

        import routing
        target_district = (routing.resolve_district(location) or "").lower()

        matched_vols = []
        for vol in all_vols:
            if vol.get("current_coordinates"):
                vol["current_coordinates"] = self._json_loads(vol["current_coordinates"])
            score = 0
            service_area = (vol.get("service_area") or "").lower()
            vol_loc = (vol.get("location") or "").lower()
            vol_district = (routing.resolve_district(vol.get("service_area") or vol.get("location") or vol.get("current_location")) or "").lower()

            if target_district and vol_district and target_district == vol_district:
                score += 30

            if loc_clean in service_area or loc_clean in vol_loc:
                score += 15
            elif any(part.strip() in service_area for part in loc_clean.split() if len(part.strip()) > 2):
                score += 5

            if score > 0:
                vol["match_score"] = score
                matched_vols.append(vol)

        matched_vols.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        return matched_vols if matched_vols else all_vols

    # --- Pickup Tasks ---

    def create_pickup_task_record(
        self,
        task_id: str,
        donation_id: str,
        org_id: str,
        pickup_loc: str,
        delivery_loc: str,
        time: str
    ) -> Dict[str, Any]:
        now = self._now()
        self._execute(
            "INSERT INTO pickup_tasks (id, donation_id, organization_id, pickup_location, delivery_location, scheduled_time, status, delivery_status, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', 'PENDING', %s, %s)",
            (task_id, donation_id, org_id, pickup_loc, delivery_loc, time, now, now)
        )
        return self.get_pickup_task_record(task_id) or {}

    def get_pickup_task_record(self, task_id: str) -> Optional[Dict[str, Any]]:
        row = self._fetchone("SELECT * FROM pickup_tasks WHERE id = %s", (task_id,))
        if row:
            if row.get("pickup_coordinates"):
                row["pickup_coordinates"] = self._json_loads(row["pickup_coordinates"])
            if row.get("destination_coordinates"):
                row["destination_coordinates"] = self._json_loads(row["destination_coordinates"])
            for f in ["pickup_distance_km", "delivery_distance_km", "total_distance_km", "estimated_transport_cost", "approved_transport_reimbursement"]:
                if row.get(f) is not None:
                    row[f] = float(row[f])
            if "pickup_location_confirmed" in row:
                row["pickup_location_confirmed"] = bool(row["pickup_location_confirmed"])
            if "destination_location_confirmed" in row:
                row["destination_location_confirmed"] = bool(row["destination_location_confirmed"])
        return row

    def get_pickup_tasks_by_donation_id(self, donation_id: str) -> List[Dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM pickup_tasks WHERE donation_id = %s ORDER BY created_at DESC", (donation_id,))
        for r in rows:
            if r.get("pickup_coordinates"):
                r["pickup_coordinates"] = self._json_loads(r["pickup_coordinates"])
            if r.get("destination_coordinates"):
                r["destination_coordinates"] = self._json_loads(r["destination_coordinates"])
        return rows

    def get_donations_by_donor_id(self, donor_id: str) -> List[Dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM donations WHERE donor_id = %s ORDER BY created_at DESC", (donor_id,))
        for r in rows:
            if "quantity" in r:
                r["quantity"] = float(r["quantity"])
        return rows

    def get_pickup_tasks_for_volunteer(self, volunteer_id: str) -> List[Dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM pickup_tasks WHERE volunteer_id = %s ORDER BY created_at DESC", (volunteer_id,))
        for r in rows:
            if r.get("pickup_coordinates"):
                r["pickup_coordinates"] = self._json_loads(r["pickup_coordinates"])
            if r.get("destination_coordinates"):
                r["destination_coordinates"] = self._json_loads(r["destination_coordinates"])
        return rows

    def get_pickup_tasks_for_organization(self, org_id: str) -> List[Dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM pickup_tasks WHERE organization_id = %s ORDER BY created_at DESC", (org_id,))
        for r in rows:
            if r.get("pickup_coordinates"):
                r["pickup_coordinates"] = self._json_loads(r["pickup_coordinates"])
            if r.get("destination_coordinates"):
                r["destination_coordinates"] = self._json_loads(r["destination_coordinates"])
        return rows

    def assign_volunteer_record(self, task_id: str, volunteer_id: str, atomic_claim: bool = False) -> bool:
        now = self._now()
        if atomic_claim:
            # Only assign if unassigned or in open status
            task = self.get_pickup_task_record(task_id)
            if not task:
                return False
            curr_vol = task.get("volunteer_id")
            curr_status = task.get("status")
            if curr_vol and curr_status not in ["PENDING", "OFFERED", "OPEN"]:
                return False

        self._execute(
            "UPDATE pickup_tasks SET volunteer_id = %s, status = 'ASSIGNED', updated_at = %s WHERE id = %s",
            (volunteer_id, now, task_id)
        )
        return True

    def update_pickup_status_record(self, task_id: str, status: str) -> bool:
        now = self._now()
        self._execute(
            "UPDATE pickup_tasks SET status = %s, updated_at = %s WHERE id = %s",
            (status, now, task_id)
        )
        return True

    # --- Notifications ---

    def create_notification_record(
        self,
        notif_id: str,
        recipient_type: str,
        recipient_id: str,
        message: str,
        channel: str
    ) -> None:
        now = self._now()
        self._execute(
            "INSERT INTO notifications (id, recipient_type, recipient_id, message, channel, status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, 'SENT', %s)",
            (notif_id, recipient_type, recipient_id, message, channel, now)
        )

    def get_notifications_for_recipient(self, recipient_id: str) -> List[Dict[str, Any]]:
        return self._fetchall("SELECT * FROM notifications WHERE recipient_id = %s ORDER BY created_at DESC", (recipient_id,))

    def get_all_donations(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if status and status.strip():
            rows = self._fetchall("SELECT * FROM donations WHERE UPPER(status) = %s ORDER BY created_at DESC", (status.strip().upper(),))
        else:
            rows = self._fetchall("SELECT * FROM donations ORDER BY created_at DESC")
        for r in rows:
            if "quantity" in r:
                r["quantity"] = float(r["quantity"])
        return rows

    def get_all_organizations(self) -> List[Dict[str, Any]]:
        return self._fetchall("SELECT * FROM organizations ORDER BY name ASC")

    def get_all_volunteers(self) -> List[Dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM volunteers ORDER BY name ASC")
        for r in rows:
            if r.get("current_coordinates"):
                r["current_coordinates"] = self._json_loads(r["current_coordinates"])
        return rows

    def get_all_pickup_tasks(self) -> List[Dict[str, Any]]:
        tasks = self._fetchall("SELECT * FROM pickup_tasks ORDER BY created_at DESC")
        for task in tasks:
            if task.get("pickup_coordinates"):
                task["pickup_coordinates"] = self._json_loads(task["pickup_coordinates"])
            if task.get("destination_coordinates"):
                task["destination_coordinates"] = self._json_loads(task["destination_coordinates"])
            if task.get("organization_id"):
                org = self.get_organization_record(task["organization_id"])
                task["organization_name"] = org.get("name") if org else None
            if task.get("volunteer_id"):
                vol = self.get_volunteer_record(task["volunteer_id"])
                task["volunteer_name"] = vol.get("name") if vol else None
        return tasks

    def get_all_notifications(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._fetchall(f"SELECT * FROM notifications ORDER BY created_at DESC LIMIT {int(limit)}")

    def get_dashboard_stats(self) -> Dict[str, Any]:
        all_dons = self.get_all_donations()
        total_donations = len(all_dons)
        total_food_quantity = sum(float(d.get("quantity", 0.0) or 0.0) for d in all_dons)
        available_donations = len([d for d in all_dons if d.get("status") == "AVAILABLE"])
        active_rescues = len([d for d in all_dons if d.get("status") in ["MATCHED", "PICKUP_PENDING", "PICKUP_ASSIGNED", "COLLECTED"]])
        delivered_rescues = len([d for d in all_dons if d.get("status") == "DELIVERED"])

        all_orgs = self.get_all_organizations()
        all_vols = self.get_all_volunteers()
        avail_vols = len([v for v in all_vols if (v.get("current_status", "").lower() == "available" or v.get("availability_status", "").upper() == "AVAILABLE")])

        status_distribution = {}
        for d in all_dons:
            st = d.get("status", "AVAILABLE")
            status_distribution[st] = status_distribution.get(st, 0) + 1

        return {
            "total_donations": total_donations,
            "total_food_quantity": round(float(total_food_quantity), 1),
            "available_donations": available_donations,
            "active_rescues": active_rescues,
            "delivered_rescues": delivered_rescues,
            "total_organizations": len(all_orgs),
            "total_volunteers": len(all_vols),
            "available_volunteers": avail_vols,
            "status_distribution": status_distribution,
        }

    def reset_database_data(self, wipe_all: bool = False) -> None:
        """Reset donations, tasks, messages, etc."""
        self._execute("DELETE FROM pickup_location_history")
        self._execute("DELETE FROM reimbursements")
        self._execute("DELETE FROM qr_codes")
        self._execute("DELETE FROM pickup_tasks")
        self._execute("DELETE FROM notifications")
        self._execute("DELETE FROM donations")
        self._execute("DELETE FROM audit_events")
        self._execute("DELETE FROM users")
        self._execute("DELETE FROM messages")
        if wipe_all:
            self._execute("DELETE FROM volunteers")
            self._execute("DELETE FROM organizations")
            self._execute("DELETE FROM donors")

    # --- Reimbursements ---

    def create_reimbursement_record(
        self,
        reimbursement_id: str,
        pickup_task_id: str,
        volunteer_id: str,
        distance_km: float,
        rate_per_km: float,
        transport_mode: str,
        amount: float,
        currency: str = "LKR",
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        now = self._now()
        self._execute(
            "INSERT INTO reimbursements (id, pickup_task_id, volunteer_id, distance_km, rate_per_km, transport_mode, amount, currency, status, created_at, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, %s)",
            (reimbursement_id, pickup_task_id, volunteer_id, float(distance_km), float(rate_per_km), str(transport_mode), float(amount), str(currency), now, notes)
        )
        return self.get_reimbursement_record(reimbursement_id) or {}

    def get_reimbursement_record(self, reimbursement_id: str) -> Optional[Dict[str, Any]]:
        row = self._fetchone("SELECT * FROM reimbursements WHERE id = %s", (reimbursement_id,))
        if row:
            for f in ["distance_km", "rate_per_km", "amount"]:
                if row.get(f) is not None:
                    row[f] = float(row[f])
        return row

    def get_reimbursement_by_pickup_id(self, pickup_task_id: str) -> Optional[Dict[str, Any]]:
        row = self._fetchone("SELECT * FROM reimbursements WHERE pickup_task_id = %s ORDER BY created_at DESC", (pickup_task_id,))
        if row:
            for f in ["distance_km", "rate_per_km", "amount"]:
                if row.get(f) is not None:
                    row[f] = float(row[f])
        return row

    def get_reimbursements_for_volunteer(self, volunteer_id: str) -> List[Dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM reimbursements WHERE volunteer_id = %s ORDER BY created_at DESC", (volunteer_id,))
        for r in rows:
            for f in ["distance_km", "rate_per_km", "amount"]:
                if r.get(f) is not None:
                    r[f] = float(r[f])
        return rows

    def get_all_reimbursements(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if status and status.strip():
            rows = self._fetchall("SELECT * FROM reimbursements WHERE UPPER(status) = %s ORDER BY created_at DESC", (status.strip().upper(),))
        else:
            rows = self._fetchall("SELECT * FROM reimbursements ORDER BY created_at DESC")
        for r in rows:
            for f in ["distance_km", "rate_per_km", "amount"]:
                if r.get(f) is not None:
                    r[f] = float(r[f])
            if r.get("volunteer_id"):
                vol = self.get_volunteer_record(r["volunteer_id"])
                r["volunteer_name"] = vol.get("name") if vol else None
        return rows

    def update_reimbursement_status_record(
        self,
        reimbursement_id: str,
        status: str,
        notes: Optional[str] = None
    ) -> bool:
        now = self._now()
        norm_status = str(status).strip().upper()
        fields = ["status = %s"]
        params = [norm_status]
        if norm_status == "APPROVED":
            fields.append("approved_at = %s")
            params.append(now)
        elif norm_status == "PAID":
            fields.append("paid_at = %s")
            params.append(now)
        if notes is not None:
            fields.append("notes = %s")
            params.append(notes)
        params.append(reimbursement_id)

        self._execute(f"UPDATE reimbursements SET {', '.join(fields)} WHERE id = %s", tuple(params))
        return True

    # --- GPS Location History ---

    def record_pickup_location(
        self,
        location_id: str,
        pickup_task_id: str,
        volunteer_id: str,
        latitude: float,
        longitude: float,
        accuracy_m: Optional[float] = None,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        ts = timestamp or self._now()
        acc = float(accuracy_m) if accuracy_m is not None else None
        self._execute(
            "INSERT INTO pickup_location_history (id, pickup_task_id, volunteer_id, latitude, longitude, accuracy_m, timestamp) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (location_id, pickup_task_id, volunteer_id, float(latitude), float(longitude), acc, ts)
        )
        return {
            "id": location_id,
            "pickup_task_id": pickup_task_id,
            "volunteer_id": volunteer_id,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "accuracy_m": acc,
            "timestamp": ts
        }

    def get_latest_pickup_location(self, pickup_task_id: str) -> Optional[Dict[str, Any]]:
        row = self._fetchone("SELECT * FROM pickup_location_history WHERE pickup_task_id = %s ORDER BY timestamp DESC LIMIT 1", (pickup_task_id,))
        if row:
            for f in ["latitude", "longitude", "accuracy_m"]:
                if row.get(f) is not None:
                    row[f] = float(row[f])
        return row

    def get_pickup_location_history(self, pickup_task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self._fetchall(f"SELECT * FROM pickup_location_history WHERE pickup_task_id = %s ORDER BY timestamp DESC LIMIT {int(limit)}", (pickup_task_id,))
        for r in rows:
            for f in ["latitude", "longitude", "accuracy_m"]:
                if r.get(f) is not None:
                    r[f] = float(r[f])
        return rows

    # --- Volunteer Availability & Coordination ---

    def update_volunteer_availability(
        self,
        volunteer_id: str,
        status: str,
        current_location: Optional[str] = None,
        current_coordinates: Optional[Dict[str, Any]] = None
    ) -> bool:
        norm_status = str(status).strip().upper()
        now = self._now()
        fields = [
            "availability_status = %s",
            "current_status = %s"
        ]
        params = [norm_status, norm_status.lower()]

        if current_location is not None:
            fields.append("current_location = %s")
            params.append(current_location)
        if current_coordinates is not None:
            fields.append("current_coordinates = %s")
            params.append(self._json_dumps(current_coordinates))
        if norm_status == "AVAILABLE":
            fields.append("last_available_at = %s")
            params.append(now)

        params.append(volunteer_id)
        self._execute(f"UPDATE volunteers SET {', '.join(fields)} WHERE id = %s", tuple(params))
        return True

    def get_available_volunteers(
        self,
        service_area: Optional[str] = None,
        min_capacity: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM volunteers WHERE UPPER(availability_status) = 'AVAILABLE' OR LOWER(current_status) = 'available'")
        vols = []
        for v in rows:
            if v.get("current_coordinates"):
                v["current_coordinates"] = self._json_loads(v["current_coordinates"])
            cap = int(v.get("vehicle_capacity", 25) or 25)
            if min_capacity and cap < min_capacity:
                continue
            if service_area and str(service_area).strip():
                sa = str(v.get("service_area", "")).lower()
                loc = str(v.get("location", "")).lower()
                target_sa = str(service_area).strip().lower()
                if target_sa not in sa and target_sa not in loc and sa not in target_sa:
                    continue
            vols.append(v)
        return vols

    def update_pickup_task_logistics(
        self,
        task_id: str,
        pickup_coordinates: Optional[Dict[str, Any]] = None,
        destination_coordinates: Optional[Dict[str, Any]] = None,
        pickup_distance_km: Optional[float] = None,
        pickup_duration_minutes: Optional[int] = None,
        delivery_distance_km: Optional[float] = None,
        delivery_duration_minutes: Optional[int] = None,
        total_distance_km: Optional[float] = None,
        estimated_transport_cost: Optional[float] = None
    ) -> bool:
        now = self._now()
        fields = ["updated_at = %s"]
        params = [now]

        if pickup_coordinates is not None:
            fields.append("pickup_coordinates = %s")
            fields.append("pickup_location_confirmed = %s")
            params.append(self._json_dumps(pickup_coordinates))
            params.append(True)
        if destination_coordinates is not None:
            fields.append("destination_coordinates = %s")
            fields.append("destination_location_confirmed = %s")
            params.append(self._json_dumps(destination_coordinates))
            params.append(True)
        if pickup_distance_km is not None:
            fields.append("pickup_distance_km = %s")
            params.append(float(pickup_distance_km))
        if pickup_duration_minutes is not None:
            fields.append("pickup_duration_minutes = %s")
            params.append(int(pickup_duration_minutes))
        if delivery_distance_km is not None:
            fields.append("delivery_distance_km = %s")
            params.append(float(delivery_distance_km))
        if delivery_duration_minutes is not None:
            fields.append("delivery_duration_minutes = %s")
            params.append(int(delivery_duration_minutes))
        if total_distance_km is not None:
            fields.append("total_distance_km = %s")
            params.append(float(total_distance_km))
        if estimated_transport_cost is not None:
            fields.append("estimated_transport_cost = %s")
            params.append(float(estimated_transport_cost))

        params.append(task_id)
        self._execute(f"UPDATE pickup_tasks SET {', '.join(fields)} WHERE id = %s", tuple(params))
        return True

    # --- Audit Trail ---

    def create_audit_event_record(
        self,
        event_id: str,
        event_type: str,
        actor: str,
        related_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        now = self._now()
        meta_str = self._json_dumps(metadata or {})
        self._execute(
            "INSERT INTO audit_events (id, event_type, actor, related_id, metadata, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (event_id, event_type, actor, related_id, meta_str, now)
        )
        return {
            "id": event_id,
            "event_type": event_type,
            "actor": actor,
            "related_id": related_id,
            "metadata": metadata or {},
            "created_at": now
        }

    def get_audit_events_for_task(self, related_id: str) -> List[Dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM audit_events WHERE related_id = %s ORDER BY created_at ASC", (related_id,))
        for r in rows:
            if r.get("metadata"):
                r["metadata"] = self._json_loads(r["metadata"])
        return rows

    # --- User Profiles & Onboarding ---

    def get_user_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        norm = self._normalize_phone(phone)
        if not norm:
            return None
        row = self._fetchone("SELECT * FROM users WHERE phone_number = %s", (norm,))
        if not row:
            all_users = self._fetchall("SELECT * FROM users")
            for u in all_users:
                u_norm = self._normalize_phone(u.get("phone_number", ""))
                if u_norm and (u_norm == norm or (len(u_norm) >= 9 and len(norm) >= 9 and u_norm[-9:] == norm[-9:])):
                    row = u
                    break

        if not row:
            vol_rec = self.get_volunteer_by_phone(norm)
            if vol_rec and vol_rec.get("name"):
                return {
                    "phone_number": norm,
                    "display_name": vol_rec["name"],
                    "preferred_language": "en",
                    "preferred_response_mode": "text",
                    "user_role": "volunteer",
                    "onboarding_completed": True,
                    "default_location": vol_rec.get("service_area") or vol_rec.get("location"),
                    "created_at": vol_rec.get("created_at") or self._now(),
                    "last_seen_at": vol_rec.get("created_at") or self._now(),
                    "active_draft": {},
                    "conversation_state": {},
                    "metadata": {},
                }
            org_rec = self.get_organization_by_phone(norm)
            if org_rec and org_rec.get("name"):
                return {
                    "phone_number": norm,
                    "display_name": org_rec["name"],
                    "preferred_language": "en",
                    "preferred_response_mode": "text",
                    "user_role": "organization",
                    "onboarding_completed": True,
                    "default_location": org_rec.get("location") or org_rec.get("service_area"),
                    "created_at": org_rec.get("created_at") or self._now(),
                    "last_seen_at": org_rec.get("created_at") or self._now(),
                    "active_draft": {},
                    "conversation_state": {},
                    "metadata": {},
                }
            donor_rec = self.get_donor_by_phone(norm)
            if donor_rec and donor_rec.get("name"):
                return {
                    "phone_number": norm,
                    "display_name": donor_rec["name"],
                    "preferred_language": "en",
                    "preferred_response_mode": "text",
                    "user_role": "donor",
                    "onboarding_completed": True,
                    "default_location": donor_rec.get("location"),
                    "created_at": donor_rec.get("created_at") or self._now(),
                    "last_seen_at": donor_rec.get("created_at") or self._now(),
                    "active_draft": {},
                    "conversation_state": {},
                    "metadata": {},
                }
            return None

        row["onboarding_completed"] = bool(row.get("onboarding_completed", False))
        row["preferred_response_mode"] = row.get("preferred_response_mode") or "text"
        row["metadata"] = self._json_loads(row.get("metadata"))
        row["conversation_state"] = self._json_loads(row.get("conversation_state"))
        row["active_draft"] = self._json_loads(row.get("active_draft"))

        # Fallback enrichment
        if not row.get("display_name") or row.get("display_name", "").startswith("User_") or row.get("user_role") in ["unknown", None, ""]:
            vol_rec = self.get_volunteer_by_phone(norm)
            if vol_rec and vol_rec.get("name"):
                row["display_name"] = vol_rec["name"]
                row["user_role"] = "volunteer"
                row["onboarding_completed"] = True
            else:
                org_rec = self.get_organization_by_phone(norm)
                if org_rec and org_rec.get("name"):
                    row["display_name"] = org_rec["name"]
                    row["user_role"] = "organization"
                    row["onboarding_completed"] = True
                else:
                    donor_rec = self.get_donor_by_phone(norm)
                    if donor_rec and donor_rec.get("name"):
                        row["display_name"] = donor_rec["name"]
                        row["user_role"] = "donor"
                        row["onboarding_completed"] = True
        return row

    def create_or_update_user(
        self,
        phone: str,
        display_name: Optional[str] = None,
        preferred_language: Optional[str] = None,
        preferred_response_mode: str = "text",
        user_role: str = "unknown",
        onboarding_completed: bool = False,
        default_location: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        norm = self._normalize_phone(phone)
        now = self._now()

        if not display_name or display_name.startswith("User_") or user_role in ["unknown", None, ""]:
            vol_rec = self.get_volunteer_by_phone(norm)
            if vol_rec and vol_rec.get("name"):
                display_name = display_name if (display_name and not display_name.startswith("User_")) else vol_rec["name"]
                user_role = "volunteer"
                onboarding_completed = True
                default_location = default_location or vol_rec.get("service_area") or vol_rec.get("location")
            else:
                org_rec = self.get_organization_by_phone(norm)
                if org_rec and org_rec.get("name"):
                    display_name = display_name if (display_name and not display_name.startswith("User_")) else org_rec["name"]
                    user_role = "organization"
                    onboarding_completed = True
                    default_location = default_location or org_rec.get("location") or org_rec.get("service_area")
                else:
                    donor_rec = self.get_donor_by_phone(norm)
                    if donor_rec and donor_rec.get("name"):
                        display_name = display_name if (display_name and not display_name.startswith("User_")) else donor_rec["name"]
                        user_role = "donor"
                        onboarding_completed = True
                        default_location = default_location or donor_rec.get("location")

        existing = self._fetchone("SELECT * FROM users WHERE phone_number = %s", (norm,))
        if existing:
            fields = ["last_seen_at = %s"]
            params = [now]
            if display_name:
                fields.append("display_name = %s")
                params.append(display_name)
            if preferred_language:
                fields.append("preferred_language = %s")
                params.append(preferred_language)
            if preferred_response_mode:
                fields.append("preferred_response_mode = %s")
                params.append(preferred_response_mode)
            if user_role and user_role != "unknown":
                fields.append("user_role = %s")
                params.append(user_role)
            if onboarding_completed:
                fields.append("onboarding_completed = %s")
                params.append(True)
            if default_location:
                fields.append("default_location = %s")
                params.append(default_location)
            if metadata:
                fields.append("metadata = %s")
                params.append(self._json_dumps(metadata))

            params.append(norm)
            self._execute(f"UPDATE users SET {', '.join(fields)} WHERE phone_number = %s", tuple(params))
        else:
            self._execute(
                "INSERT INTO users (phone_number, display_name, preferred_language, preferred_response_mode, user_role, onboarding_completed, default_location, first_seen_at, last_seen_at, metadata, conversation_state, active_draft) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    norm,
                    display_name or f"User_{norm[-4:]}",
                    preferred_language or "en",
                    preferred_response_mode or "text",
                    user_role,
                    bool(onboarding_completed),
                    default_location,
                    now,
                    now,
                    self._json_dumps(metadata or {}),
                    self._json_dumps({}),
                    self._json_dumps({})
                )
            )
        return self.get_user_by_phone(norm) or {}

    def update_user_profile(
        self,
        phone: str,
        display_name: Optional[str] = None,
        preferred_language: Optional[str] = None,
        preferred_response_mode: Optional[str] = None,
        user_role: Optional[str] = None,
        default_location: Optional[str] = None,
        active_donation_id: Optional[str] = None,
        active_task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        norm = self._normalize_phone(phone)
        now = self._now()
        existing = self._fetchone("SELECT * FROM users WHERE phone_number = %s", (norm,))
        if not existing:
            self._execute(
                "INSERT INTO users (phone_number, display_name, preferred_language, preferred_response_mode, user_role, default_location, active_donation_id, active_task_id, conversation_state, active_draft, onboarding_completed, first_seen_at, last_seen_at, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    norm,
                    display_name or f"User_{norm[-4:]}",
                    preferred_language or "en",
                    preferred_response_mode or "text",
                    user_role or "unknown",
                    default_location,
                    active_donation_id,
                    active_task_id,
                    self._json_dumps({}),
                    self._json_dumps({}),
                    False,
                    now,
                    now,
                    self._json_dumps(metadata or {})
                )
            )
        else:
            fields = ["last_seen_at = %s"]
            params = [now]
            if display_name is not None:
                fields.append("display_name = %s")
                params.append(display_name)
            if preferred_language is not None:
                fields.append("preferred_language = %s")
                params.append(preferred_language)
            if preferred_response_mode is not None:
                fields.append("preferred_response_mode = %s")
                params.append(preferred_response_mode)
            if user_role is not None:
                fields.append("user_role = %s")
                params.append(user_role)
            if default_location is not None:
                fields.append("default_location = %s")
                params.append(default_location)
            if active_donation_id is not None:
                fields.append("active_donation_id = %s")
                params.append(active_donation_id)
            if active_task_id is not None:
                fields.append("active_task_id = %s")
                params.append(active_task_id)
            if metadata is not None:
                fields.append("metadata = %s")
                params.append(self._json_dumps(metadata))

            params.append(norm)
            self._execute(f"UPDATE users SET {', '.join(fields)} WHERE phone_number = %s", tuple(params))
        return self.get_user_by_phone(norm) or {}

    def set_user_language(self, phone: str, language: str) -> bool:
        norm = self._normalize_phone(phone)
        now = self._now()
        existing = self._fetchone("SELECT * FROM users WHERE phone_number = %s", (norm,))
        if existing:
            self._execute("UPDATE users SET preferred_language = %s, last_seen_at = %s WHERE phone_number = %s", (language.lower().strip(), now, norm))
        else:
            self.create_or_update_user(norm, preferred_language=language.lower().strip())
        return True

    def set_user_response_mode(self, phone: str, mode: str) -> bool:
        norm = self._normalize_phone(phone)
        now = self._now()
        clean_mode = "voice" if "voice" in mode.lower() else "text"
        existing = self._fetchone("SELECT * FROM users WHERE phone_number = %s", (norm,))
        if existing:
            self._execute("UPDATE users SET preferred_response_mode = %s, last_seen_at = %s WHERE phone_number = %s", (clean_mode, now, norm))
        else:
            self.create_or_update_user(norm, preferred_response_mode=clean_mode)
        return True

    def set_onboarding_completed(self, phone: str, completed: bool = True) -> bool:
        norm = self._normalize_phone(phone)
        now = self._now()
        self._execute("UPDATE users SET onboarding_completed = %s, last_seen_at = %s WHERE phone_number = %s", (bool(completed), now, norm))
        return True

    def get_user_conversation_state(self, phone: str) -> Dict[str, Any]:
        user = self.get_user_by_phone(phone)
        if user and isinstance(user.get("conversation_state"), dict):
            return user["conversation_state"]
        return {}

    def set_user_conversation_state(self, phone: str, state: Dict[str, Any]) -> bool:
        norm = self._normalize_phone(phone)
        now = self._now()
        state_str = self._json_dumps(state or {})
        existing = self._fetchone("SELECT * FROM users WHERE phone_number = %s", (norm,))
        if existing:
            self._execute("UPDATE users SET conversation_state = %s, last_seen_at = %s WHERE phone_number = %s", (state_str, now, norm))
        else:
            self.create_or_update_user(norm)
            self._execute("UPDATE users SET conversation_state = %s, last_seen_at = %s WHERE phone_number = %s", (state_str, now, norm))
        return True

    def clear_user_conversation_state(self, phone: str) -> bool:
        return self.set_user_conversation_state(phone, {})

    def save_draft_donation(self, phone: str, draft_data: Dict[str, Any]) -> Dict[str, Any]:
        norm = self._normalize_phone(phone)
        user = self.get_user_by_phone(norm)
        existing_draft = (user.get("active_draft") or {}) if user else {}
        if not isinstance(existing_draft, dict):
            existing_draft = {}
        merged = dict(existing_draft)
        for k, v in draft_data.items():
            if v is not None:
                merged[k] = v
        now = self._now()
        draft_str = self._json_dumps(merged)
        existing = self._fetchone("SELECT * FROM users WHERE phone_number = %s", (norm,))
        if existing:
            self._execute("UPDATE users SET active_draft = %s, last_seen_at = %s WHERE phone_number = %s", (draft_str, now, norm))
        else:
            self.create_or_update_user(norm)
            self._execute("UPDATE users SET active_draft = %s, last_seen_at = %s WHERE phone_number = %s", (draft_str, now, norm))
        return merged

    def get_draft_donation(self, phone: str) -> Optional[Dict[str, Any]]:
        user = self.get_user_by_phone(phone)
        if user and user.get("active_draft"):
            draft = user["active_draft"]
            if isinstance(draft, dict) and any(draft.values()):
                return draft
        return None

    def clear_draft_donation(self, phone: str) -> bool:
        norm = self._normalize_phone(phone)
        now = self._now()
        self._execute("UPDATE users SET active_draft = %s, last_seen_at = %s WHERE phone_number = %s", (self._json_dumps({}), now, norm))
        return True

    def get_all_users(self) -> List[Dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM users ORDER BY last_seen_at DESC")
        users = []
        seen_phones = set()
        for r in rows:
            norm = r.get("phone_number", "")
            if norm:
                seen_phones.add(norm)
            r["onboarding_completed"] = bool(r.get("onboarding_completed", False))
            r["preferred_response_mode"] = r.get("preferred_response_mode") or "text"
            r["metadata"] = self._json_loads(r.get("metadata"))
            r["conversation_state"] = self._json_loads(r.get("conversation_state"))
            r["active_draft"] = self._json_loads(r.get("active_draft"))

            # Enrich display_name and user_role
            if not r.get("display_name") or r.get("display_name", "").startswith("User_") or r.get("user_role") in ["unknown", None, ""]:
                vol_rec = self.get_volunteer_by_phone(norm)
                if vol_rec and vol_rec.get("name"):
                    r["display_name"] = vol_rec["name"]
                    r["user_role"] = "volunteer"
                    r["onboarding_completed"] = True
                else:
                    org_rec = self.get_organization_by_phone(norm)
                    if org_rec and org_rec.get("name"):
                        r["display_name"] = org_rec["name"]
                        r["user_role"] = "organization"
                        r["onboarding_completed"] = True
                    else:
                        donor_rec = self.get_donor_by_phone(norm)
                        if donor_rec and donor_rec.get("name"):
                            r["display_name"] = donor_rec["name"]
                            r["user_role"] = "donor"
                            r["onboarding_completed"] = True
            users.append(r)

        # Include registered volunteers not in users
        for vol in self.get_all_volunteers():
            v_phone = self._normalize_phone(vol.get("phone", ""))
            if v_phone and v_phone not in seen_phones:
                users.append({
                    "phone_number": v_phone,
                    "display_name": vol.get("name", "Volunteer"),
                    "preferred_language": "en",
                    "preferred_response_mode": "text",
                    "user_role": "volunteer",
                    "onboarding_completed": True,
                    "default_location": vol.get("service_area") or vol.get("location"),
                    "created_at": vol.get("created_at") or self._now(),
                    "last_seen_at": vol.get("created_at") or self._now(),
                    "active_draft": {},
                    "conversation_state": {},
                    "metadata": {},
                })
                seen_phones.add(v_phone)

        # Include registered orgs not in users
        for org in self.get_all_organizations():
            o_phone = self._normalize_phone(org.get("phone", ""))
            if o_phone and o_phone not in seen_phones:
                users.append({
                    "phone_number": o_phone,
                    "display_name": org.get("name", "Organization"),
                    "preferred_language": "en",
                    "preferred_response_mode": "text",
                    "user_role": "organization",
                    "onboarding_completed": True,
                    "default_location": org.get("location") or org.get("service_area"),
                    "created_at": org.get("created_at") or self._now(),
                    "last_seen_at": org.get("created_at") or self._now(),
                    "active_draft": {},
                    "conversation_state": {},
                    "metadata": {},
                })
                seen_phones.add(o_phone)

        # Include registered donors not in users
        for don in self.get_all_donors():
            d_phone = self._normalize_phone(don.get("phone", ""))
            if d_phone and d_phone not in seen_phones:
                users.append({
                    "phone_number": d_phone,
                    "display_name": don.get("name", "Donor"),
                    "preferred_language": "en",
                    "preferred_response_mode": "text",
                    "user_role": "donor",
                    "onboarding_completed": True,
                    "default_location": don.get("location"),
                    "created_at": don.get("created_at") or self._now(),
                    "last_seen_at": don.get("created_at") or self._now(),
                    "active_draft": {},
                    "conversation_state": {},
                    "metadata": {},
                })
                seen_phones.add(d_phone)

        return users

    def get_all_donors(self) -> List[Dict[str, Any]]:
        return self._fetchall("SELECT * FROM donors ORDER BY created_at DESC")

    # --- Messages & Conversations ---

    def record_message(
        self,
        phone: str,
        sender: str,
        text: str,
        is_voice: bool = False,
        transcript: Optional[str] = None,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        norm = self._normalize_phone(phone)
        msg_id = f"msg-{uuid.uuid4().hex[:8]}"
        ts = timestamp or self._now()
        self._execute(
            "INSERT INTO messages (id, phone_number, sender, message_text, is_voice, transcript, timestamp) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (msg_id, norm, sender, text, bool(is_voice), transcript, ts)
        )

        existing = self._fetchone("SELECT * FROM users WHERE phone_number = %s", (norm,))
        if existing:
            self._execute("UPDATE users SET last_seen_at = %s WHERE phone_number = %s", (ts, norm))
        else:
            self.create_or_update_user(
                norm,
                preferred_response_mode="voice" if is_voice else "text"
            )

        return {
            "id": msg_id,
            "phone_number": norm,
            "sender": sender,
            "message_text": text,
            "is_voice": bool(is_voice),
            "transcript": transcript,
            "timestamp": ts
        }

    def get_all_conversations(self) -> List[Dict[str, Any]]:
        users = self.get_all_users()
        conversations = []

        for u in users:
            norm = u["phone_number"]
            latest_msg = self._fetchone("SELECT * FROM messages WHERE phone_number = %s ORDER BY timestamp DESC LIMIT 1", (norm,))
            msg_count = len(self._fetchall("SELECT id FROM messages WHERE phone_number = %s", (norm,)))

            disp_name = u.get("display_name") or f"User_{norm[-4:]}"
            u_role = u.get("user_role", "unknown")
            if not disp_name or disp_name.startswith("User_") or u_role in ["unknown", None, ""]:
                donor_rec = self.get_donor_by_phone(norm)
                if donor_rec and donor_rec.get("name"):
                    disp_name = donor_rec["name"]
                    u_role = "donor"
                else:
                    vol_rec = self.get_volunteer_by_phone(norm)
                    if vol_rec and vol_rec.get("name"):
                        disp_name = vol_rec["name"]
                        u_role = "volunteer"
                    else:
                        org_rec = self.get_organization_by_phone(norm)
                        if org_rec and org_rec.get("name"):
                            disp_name = org_rec["name"]
                            u_role = "organization"

            conversations.append({
                "phone_number": norm,
                "display_name": disp_name,
                "user_role": u_role,
                "preferred_language": u.get("preferred_language", "en"),
                "preferred_response_mode": u.get("preferred_response_mode", "text"),
                "message_count": msg_count,
                "last_message": latest_msg.get("message_text", "") if latest_msg else "Conversation initiated",
                "last_message_sender": latest_msg.get("sender", "system") if latest_msg else "system",
                "last_message_is_voice": bool(latest_msg.get("is_voice", False)) if latest_msg else False,
                "last_activity": latest_msg.get("timestamp") if latest_msg else u.get("last_seen_at", self._now()),
                "onboarding_completed": bool(u.get("onboarding_completed", False)),
            })

        conversations.sort(key=lambda c: str(c.get("last_activity", "")), reverse=True)
        return conversations

    def get_conversation_messages(self, phone: str, limit: int = 100) -> List[Dict[str, Any]]:
        norm = self._normalize_phone(phone)
        rows = self._fetchall(f"SELECT * FROM messages WHERE phone_number = %s ORDER BY timestamp ASC LIMIT {int(limit)}", (norm,))
        for r in rows:
            r["is_voice"] = bool(r.get("is_voice", False))
        return rows

    def get_all_audit_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self._fetchall(f"SELECT * FROM audit_events ORDER BY created_at DESC LIMIT {int(limit)}")
        for r in rows:
            if r.get("metadata"):
                r["metadata"] = self._json_loads(r["metadata"])
        return rows

    # --- System Settings ---

    def get_transport_settings(self) -> Dict[str, Any]:
        row = self._fetchone("SELECT setting_value FROM system_settings WHERE setting_key = %s", ("transport_cost",))
        if row and row.get("setting_value"):
            val = self._json_loads(row["setting_value"])
            if isinstance(val, dict):
                return val
        return {
            "base_fare": 100.0,
            "cost_per_km": 80.0,
            "currency": "LKR",
            "rates_by_vehicle": {
                "Motorbike": 50.0,
                "Three-Wheeler": 90.0,
                "Car": 80.0,
                "Van": 120.0,
                "Bicycle": 25.0,
                "Electric Bike": 25.0
            },
            "vehicle_multipliers": {
                "Motorbike": 1.0,
                "Bicycle": 0.6,
                "Car": 1.5,
                "Van": 2.0,
                "Three-Wheeler": 1.2
            }
        }

    def update_transport_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        now = self._now()
        val_str = self._json_dumps(settings)
        existing = self._fetchone("SELECT setting_key FROM system_settings WHERE setting_key = %s", ("transport_cost",))
        if existing:
            self._execute("UPDATE system_settings SET setting_value = %s, updated_at = %s WHERE setting_key = %s", (val_str, now, "transport_cost"))
        else:
            self._execute("INSERT INTO system_settings (setting_key, setting_value, updated_at) VALUES (%s, %s, %s)", ("transport_cost", val_str, now))
        return settings

    # --- QR Code Handover Verification ---

    def create_qr_code_record(
        self,
        qr_id: str,
        task_id: str,
        donation_id: str,
        qr_type: str,
        token: str,
        token_hash: str,
        donor_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        assigned_volunteer_id: Optional[str] = None,
        status: str = "ACTIVE",
        created_at: Optional[str] = None,
        expires_at: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        now = created_at or self._now()
        meta_str = self._json_dumps(metadata or {})
        existing = self._fetchone("SELECT id FROM qr_codes WHERE id = %s", (qr_id,))
        try:
            if existing:
                self._execute(
                    "UPDATE qr_codes SET task_id = %s, donation_id = %s, qr_type = %s, token = %s, token_hash = %s, "
                    "donor_id = %s, organization_id = %s, assigned_volunteer_id = %s, status = %s, expires_at = %s, metadata = %s WHERE id = %s",
                    (task_id, donation_id, qr_type.upper(), token, token_hash, donor_id, organization_id, assigned_volunteer_id, status.upper(), expires_at, meta_str, qr_id)
                )
            else:
                self._execute(
                    "INSERT INTO qr_codes (id, task_id, donation_id, qr_type, token, token_hash, donor_id, organization_id, assigned_volunteer_id, status, created_at, expires_at, metadata) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (qr_id, task_id, donation_id, qr_type.upper(), token, token_hash, donor_id, organization_id, assigned_volunteer_id, status.upper(), now, expires_at, meta_str)
                )
        except Exception:
            return {
                "id": qr_id,
                "task_id": task_id,
                "donation_id": donation_id,
                "qr_type": qr_type.upper(),
                "token": token,
                "token_hash": token_hash,
                "status": status.upper(),
            }
        return self.get_qr_code_by_id(qr_id) or {}

    def get_qr_code_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        row = self._fetchone("SELECT * FROM qr_codes WHERE token = %s", (token.strip(),))
        if row and row.get("metadata"):
            row["metadata"] = self._json_loads(row["metadata"])
        return row

    def get_qr_codes_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM qr_codes WHERE task_id = %s ORDER BY created_at ASC", (task_id,))
        for r in rows:
            if r.get("metadata"):
                r["metadata"] = self._json_loads(r["metadata"])
        return rows

    def get_qr_code_by_id(self, qr_id: str) -> Optional[Dict[str, Any]]:
        row = self._fetchone("SELECT * FROM qr_codes WHERE id = %s", (qr_id,))
        if row and row.get("metadata"):
            row["metadata"] = self._json_loads(row["metadata"])
        return row

    def get_all_qr_codes(
        self,
        status: Optional[str] = None,
        qr_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM qr_codes"
        conditions = []
        params = []
        if status:
            conditions.append("UPPER(status) = %s")
            params.append(status.upper())
        if qr_type:
            conditions.append("UPPER(qr_type) = %s")
            params.append(qr_type.upper())
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"
        rows = self._fetchall(query, tuple(params) if params else None)
        for r in rows:
            if r.get("metadata"):
                r["metadata"] = self._json_loads(r["metadata"])
        return rows

    def verify_qr_code_record(
        self,
        token: str,
        volunteer_id: Optional[str] = None,
        gps_coords: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Atomically verify a physical handover QR code and advance task lifecycle status."""
        qr = self.get_qr_code_by_token(token)
        if not qr:
            return {"success": False, "error": "INVALID_TOKEN", "message": "This FoodRescue verification code is not valid."}

        qr_status = qr.get("status", "ACTIVE")
        if qr_status == "VERIFIED":
            return {"success": False, "error": "ALREADY_USED", "message": "This handover QR code has already been verified."}
        if qr_status == "EXPIRED":
            return {"success": False, "error": "EXPIRED", "message": "This QR code has expired. Please request a new verification code."}
        if qr_status != "ACTIVE":
            return {"success": False, "error": "INACTIVE", "message": f"This QR code is {qr_status} and cannot be verified."}

        task_id = qr.get("task_id")
        task = self.get_pickup_task_record(task_id)
        if not task:
            return {"success": False, "error": "TASK_NOT_FOUND", "message": "Associated pickup task not found."}

        donation_id = qr.get("donation_id")
        qr_type = qr.get("qr_type", "PICKUP").upper()
        now = self._now()
        effective_vol_id = volunteer_id or qr.get("assigned_volunteer_id") or task.get("volunteer_id")

        # Authorization: verify volunteer matches assigned volunteer if provided
        assigned_vol_id = task.get("volunteer_id") or qr.get("assigned_volunteer_id")
        if volunteer_id and assigned_vol_id:
            vol_assigned = self.get_volunteer_record(assigned_vol_id) or self.get_volunteer_by_phone(assigned_vol_id)
            v_provided = self.get_volunteer_record(volunteer_id) or self.get_volunteer_by_phone(volunteer_id)
            if vol_assigned and v_provided and vol_assigned.get("id") != v_provided.get("id"):
                return {"success": False, "error": "UNAUTHORIZED_VOLUNTEER", "message": "This QR code belongs to another assigned volunteer."}

        if qr_type == "PICKUP":
            if task.get("status") in ["COLLECTED", "IN_TRANSIT", "DELIVERED", "COMPLETED"]:
                return {"success": False, "error": "ALREADY_COLLECTED", "message": "This donation has already been collected."}

            self._execute(
                "UPDATE qr_codes SET status = 'VERIFIED', verified_at = %s, verified_by = %s WHERE token = %s AND status = 'ACTIVE'",
                (now, effective_vol_id, token.strip())
            )
            self._execute(
                "UPDATE pickup_tasks SET status = 'COLLECTED', delivery_status = 'IN_TRANSIT', food_collected_at = %s, updated_at = %s WHERE id = %s",
                (now, now, task_id)
            )
            if donation_id:
                self._execute(
                    "UPDATE donations SET status = 'COLLECTED', updated_at = %s WHERE id = %s",
                    (now, donation_id)
                )

            self.create_audit_event_record(
                event_id=f"aud-{uuid.uuid4().hex[:8]}",
                event_type="PICKUP_QR_VERIFIED",
                actor=str(effective_vol_id or "volunteer"),
                related_id=task_id,
                metadata={"token": token, "gps": gps_coords}
            )

        elif qr_type == "DELIVERY":
            if task.get("status") not in ["COLLECTED", "IN_TRANSIT"]:
                if task.get("status") in ["DELIVERED", "COMPLETED"]:
                    return {"success": False, "error": "ALREADY_DELIVERED", "message": "This delivery has already been completed."}
                return {"success": False, "error": "NOT_YET_COLLECTED", "message": "Cannot verify delivery before the food has been collected from the donor."}

            self._execute(
                "UPDATE qr_codes SET status = 'VERIFIED', verified_at = %s, verified_by = %s WHERE token = %s AND status = 'ACTIVE'",
                (now, effective_vol_id, token.strip())
            )
            self._execute(
                "UPDATE pickup_tasks SET status = 'COMPLETED', delivery_status = 'DELIVERED', food_delivered_at = %s, updated_at = %s WHERE id = %s",
                (now, now, task_id)
            )
            if donation_id:
                self._execute(
                    "UPDATE donations SET status = 'DELIVERED', updated_at = %s WHERE id = %s",
                    (now, donation_id)
                )

            if effective_vol_id:
                self._execute(
                    "UPDATE volunteers SET current_status = 'available', availability_status = 'AVAILABLE' WHERE id = %s OR phone = %s",
                    (effective_vol_id, effective_vol_id)
                )

            self.create_audit_event_record(
                event_id=f"aud-{uuid.uuid4().hex[:8]}",
                event_type="DELIVERY_QR_VERIFIED",
                actor=str(effective_vol_id or "volunteer"),
                related_id=task_id,
                metadata={"token": token, "gps": gps_coords}
            )

        updated_task = self.get_pickup_task_record(task_id)
        return {
            "success": True,
            "qr_type": qr_type,
            "task_id": task_id,
            "donation_id": donation_id,
            "verified_at": now,
            "verified_by": effective_vol_id,
            "task": updated_task,
        }

    def delete_donation_record(self, donation_id: str) -> bool:
        """Delete a food donation record and its linked tasks/QR codes."""
        try:
            self._execute("DELETE FROM qr_codes WHERE donation_id = %s", (donation_id,))
            self._execute("DELETE FROM pickup_tasks WHERE donation_id = %s", (donation_id,))
            self._execute("DELETE FROM donations WHERE id = %s", (donation_id,))
            return True
        except Exception as err:
            logger.error(f"Error deleting donation {donation_id}: {err}")
            return False

    def delete_donor_record(self, donor_id: str) -> bool:
        """Delete a donor record."""
        try:
            self._execute("DELETE FROM donors WHERE id = %s", (donor_id,))
            return True
        except Exception as err:
            logger.error(f"Error deleting donor {donor_id}: {err}")
            return False

    def delete_organization_record(self, org_id: str) -> bool:
        """Delete an organization record."""
        try:
            self._execute("DELETE FROM organizations WHERE id = %s", (org_id,))
            return True
        except Exception as err:
            logger.error(f"Error deleting organization {org_id}: {err}")
            return False

    def delete_volunteer_record(self, volunteer_id: str) -> bool:
        """Delete a volunteer record."""
        try:
            self._execute("DELETE FROM volunteers WHERE id = %s", (volunteer_id,))
            return True
        except Exception as err:
            logger.error(f"Error deleting volunteer {volunteer_id}: {err}")
            return False

    def delete_user_record(self, phone: str) -> bool:
        """Delete a user profile and active state."""
        try:
            clean_phone = phone.replace("whatsapp:", "").strip()
            self._execute("DELETE FROM users WHERE phone = %s", (clean_phone,))
            return True
        except Exception as err:
            logger.error(f"Error deleting user {phone}: {err}")
            return False

    def delete_pickup_task_record(self, task_id: str) -> bool:
        """Delete a pickup task record."""
        try:
            self._execute("DELETE FROM qr_codes WHERE task_id = %s", (task_id,))
            self._execute("DELETE FROM pickup_tasks WHERE id = %s", (task_id,))
            return True
        except Exception as err:
            logger.error(f"Error deleting task {task_id}: {err}")
            return False

