"""FoodRescue AI SQLite Repository Implementation.

Encapsulates all SQLite storage operations, table setups, transactional CRUD,
and ranking algorithms.
"""

import sqlite3
import os
import datetime
import json
from typing import List, Dict, Any, Optional
from db_base import BaseRepository

DB_PATH = "foodrescue.db"


class SQLiteRepository(BaseRepository):
    """SQLite implementation of the FoodRescue persistence repository."""

    def __init__(self, db_path: Optional[str] = None):
        self._custom_db_path = db_path

    @property
    def db_path(self) -> str:
        if self._custom_db_path:
            return self._custom_db_path
        import database
        return os.environ.get("FOODRESCUE_DB_PATH", getattr(database, "DB_PATH", DB_PATH))


    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn


    def _now(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def setup_database(self) -> None:
        conn = self._get_connection()
        with conn:
            cursor = conn.cursor()

            # Donors
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS donors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT,
                organization_name TEXT,
                location TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            ''')

            # Organizations
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT,
                service_area TEXT NOT NULL,
                accepted_food_types TEXT NOT NULL,
                capacity TEXT,
                availability TEXT,
                location TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            ''')

            # Volunteers
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS volunteers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT,
                service_area TEXT NOT NULL,
                availability TEXT,
                current_status TEXT NOT NULL,
                location TEXT NOT NULL,
                transport_mode TEXT DEFAULT 'Motorbike',
                availability_status TEXT DEFAULT 'AVAILABLE',
                current_location TEXT,
                current_coordinates TEXT,
                vehicle_capacity INTEGER DEFAULT 25,
                completed_pickups INTEGER DEFAULT 0,
                last_available_at TEXT,
                created_at TEXT NOT NULL
            )
            ''')

            # Donations
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS donations (
                id TEXT PRIMARY KEY,
                donor_id TEXT NOT NULL,
                food_type TEXT NOT NULL,
                quantity REAL NOT NULL CHECK(quantity > 0),
                unit TEXT NOT NULL,
                dietary_information TEXT,
                pickup_location TEXT NOT NULL,
                available_from TEXT NOT NULL,
                pickup_deadline TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            ''')

            # Pickup Tasks
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS pickup_tasks (
                id TEXT PRIMARY KEY,
                donation_id TEXT NOT NULL,
                organization_id TEXT NOT NULL,
                volunteer_id TEXT,
                pickup_location TEXT NOT NULL,
                pickup_coordinates TEXT,
                pickup_location_confirmed INTEGER DEFAULT 0,
                delivery_location TEXT NOT NULL,
                destination_coordinates TEXT,
                destination_location_confirmed INTEGER DEFAULT 0,
                pickup_distance_km REAL DEFAULT 0.0,
                pickup_duration_minutes INTEGER DEFAULT 0,
                delivery_distance_km REAL DEFAULT 0.0,
                delivery_duration_minutes INTEGER DEFAULT 0,
                total_distance_km REAL DEFAULT 0.0,
                estimated_transport_cost REAL DEFAULT 0.0,
                approved_transport_reimbursement REAL DEFAULT 0.0,
                delivery_status TEXT DEFAULT 'PENDING',
                volunteer_accepted_at TEXT,
                food_collected_at TEXT,
                food_delivered_at TEXT,
                scheduled_time TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            ''')

            # Notifications
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                recipient_type TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                message TEXT NOT NULL,
                channel TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            ''')

            # Audit Events
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                related_id TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
            ''')

            # Reimbursements (Accounting Ledger)
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS reimbursements (
                id TEXT PRIMARY KEY,
                pickup_task_id TEXT NOT NULL,
                volunteer_id TEXT NOT NULL,
                distance_km REAL NOT NULL,
                rate_per_km REAL NOT NULL,
                transport_mode TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'LKR',
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TEXT NOT NULL,
                approved_at TEXT,
                paid_at TEXT,
                notes TEXT
            )
            ''')

            # Pickup Location History (GPS Breadcrumbs)
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS pickup_location_history (
                id TEXT PRIMARY KEY,
                pickup_task_id TEXT NOT NULL,
                volunteer_id TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                accuracy_m REAL,
                timestamp TEXT NOT NULL
            )
            ''')

            # Persistent Users & Onboarding Profiles
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                phone_number TEXT PRIMARY KEY,
                display_name TEXT,
                preferred_language TEXT DEFAULT 'en',
                preferred_response_mode TEXT DEFAULT 'text',
                user_role TEXT DEFAULT 'unknown',
                default_location TEXT,
                active_donation_id TEXT,
                active_task_id TEXT,
                conversation_state TEXT,
                active_draft TEXT,
                onboarding_completed INTEGER DEFAULT 0,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                metadata TEXT
            )
            ''')

            # WhatsApp & Web Chat Message History
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                phone_number TEXT NOT NULL,
                sender TEXT NOT NULL,
                message_text TEXT NOT NULL,
                is_voice INTEGER DEFAULT 0,
                transcript TEXT,
                timestamp TEXT NOT NULL
            )
            ''')

            # System Settings & Dynamic Transport Configuration
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            ''')

            # Table migrations for existing sqlite databases
            vol_cols = [
                ("transport_mode", "TEXT DEFAULT 'Motorbike'"),
                ("availability_status", "TEXT DEFAULT 'AVAILABLE'"),
                ("current_location", "TEXT"),
                ("current_coordinates", "TEXT"),
                ("vehicle_capacity", "INTEGER DEFAULT 25"),
                ("completed_pickups", "INTEGER DEFAULT 0"),
                ("last_available_at", "TEXT"),
            ]
            for col_name, col_def in vol_cols:
                try:
                    cursor.execute(f"ALTER TABLE volunteers ADD COLUMN {col_name} {col_def}")
                except sqlite3.OperationalError:
                    pass

            task_cols = [
                ("pickup_coordinates", "TEXT"),
                ("pickup_location_confirmed", "INTEGER DEFAULT 0"),
                ("destination_coordinates", "TEXT"),
                ("destination_location_confirmed", "INTEGER DEFAULT 0"),
                ("pickup_distance_km", "REAL DEFAULT 0.0"),
                ("pickup_duration_minutes", "INTEGER DEFAULT 0"),
                ("delivery_distance_km", "REAL DEFAULT 0.0"),
                ("delivery_duration_minutes", "INTEGER DEFAULT 0"),
                ("total_distance_km", "REAL DEFAULT 0.0"),
                ("estimated_transport_cost", "REAL DEFAULT 0.0"),
                ("approved_transport_reimbursement", "REAL DEFAULT 0.0"),
                ("delivery_status", "TEXT DEFAULT 'PENDING'"),
                ("volunteer_accepted_at", "TEXT"),
                ("food_collected_at", "TEXT"),
                ("food_delivered_at", "TEXT"),
            ]
            for col_name, col_def in task_cols:
                try:
                    cursor.execute(f"ALTER TABLE pickup_tasks ADD COLUMN {col_name} {col_def}")
                except sqlite3.OperationalError:
                    pass

            user_cols = [
                ("preferred_response_mode", "TEXT DEFAULT 'text'"),
                ("default_location", "TEXT"),
                ("active_donation_id", "TEXT"),
                ("active_task_id", "TEXT"),
                ("conversation_state", "TEXT"),
                ("active_draft", "TEXT"),
            ]
            for col_name, col_def in user_cols:
                try:
                    cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
                except sqlite3.OperationalError:
                    pass

            # Purge any legacy placeholder organizations
            cursor.execute("DELETE FROM organizations WHERE phone = '94770000000' OR name = 'Community Organization'")

            # Seed default system settings if not present
            cursor.execute("SELECT COUNT(*) FROM system_settings WHERE setting_key = 'transport_cost'")
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO system_settings (setting_key, setting_value, updated_at) VALUES (?, ?, ?)",
                    ("transport_cost", json.dumps({
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
                    }), self._now())
                )

        conn.close()

    def seed_test_data(self) -> None:
        conn = self._get_connection()
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO donors (id, name, phone, organization_name, location, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("d1", "Grand Hotel", "+94112345678", "Grand Hotel Colombo", "Colombo", self._now())
            )
            cursor.execute(
                "INSERT OR IGNORE INTO donors (id, name, phone, organization_name, location, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("d2", "City Bakery", "+94112345679", "City Bakery Colombo", "Colombo 4", self._now())
            )

            cursor.execute(
                "INSERT OR IGNORE INTO organizations (id, name, phone, service_area, accepted_food_types, capacity, availability, location, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("o1", "Community Kitchen Colombo", "+9419876543", "Colombo, Dehiwala", "vegetarian, non-vegetarian, lunch packets, cooked meals, bakery items", "200 meals", "always", "Colombo 7", self._now())
            )
            cursor.execute(
                "INSERT OR IGNORE INTO organizations (id, name, phone, service_area, accepted_food_types, capacity, availability, location, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("o2", "Hope Food Bank", "+9419876544", "Colombo 3, Colombo 4, Wellawatte", "dry rations, bakery items, vegetarian", "100 meals", "daytime", "Colombo 4", self._now())
            )

            cursor.execute(
                "INSERT OR IGNORE INTO volunteers (id, name, phone, service_area, availability, current_status, location, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("v1", "Amara Silva", "+94771234567", "Colombo, Colombo 3, Colombo 4, Colombo 7", "immediate, evenings", "available", "Colombo 3", self._now())
            )
            cursor.execute(
                "INSERT OR IGNORE INTO volunteers (id, name, phone, service_area, availability, current_status, location, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("v2", "Kamal Perera", "+94771234568", "Colombo, Dehiwala, Mount Lavinia", "weekends, evenings", "available", "Colombo 5", self._now())
            )

        conn.close()

    def _normalize_phone(self, phone: str) -> str:
        if not phone:
            return ""
        return "".join(ch for ch in str(phone) if ch.isdigit())

    def get_donor_record(self, donor_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM donors WHERE id = ?", (donor_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_donor_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        if not phone:
            return None
        norm_digits = self._normalize_phone(phone)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM donors")
        rows = cursor.fetchall()
        conn.close()
        for row in rows:
            d = dict(row)
            d_digits = self._normalize_phone(d.get("phone", ""))
            if d_digits and norm_digits and (d_digits == norm_digits or d_digits.endswith(norm_digits) or norm_digits.endswith(d_digits)):
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
        conn = self._get_connection()
        now = self._now()
        org_name = organization_name or name
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO donors (id, name, phone, organization_name, location, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (donor_id, name, phone, org_name, location, now))
        
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM donors WHERE id = ?", (donor_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}

    def get_organization_record(self, org_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM organizations WHERE id = ?", (org_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_organization_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        if not phone:
            return None
        norm_digits = self._normalize_phone(phone)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM organizations")
        rows = cursor.fetchall()
        conn.close()
        for row in rows:
            o = dict(row)
            o_digits = self._normalize_phone(o.get("phone", ""))
            if o_digits and norm_digits and (o_digits == norm_digits or o_digits.endswith(norm_digits) or norm_digits.endswith(o_digits)):
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
        conn = self._get_connection()
        now = self._now()
        loc = location or service_area.split(",")[0].strip()
        cap_val = capacity if (capacity and str(capacity).strip()) else "As needed"
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO organizations (id, name, phone, service_area, accepted_food_types, capacity, availability, location, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (org_id, name, phone, service_area, accepted_food_types, cap_val, availability or "daytime", loc, now))

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM organizations WHERE id = ?", (org_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}

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
        conn = self._get_connection()
        fields = []
        params = []
        if name is not None:
            fields.append("name = ?")
            params.append(name)
        if phone is not None:
            fields.append("phone = ?")
            params.append(phone)
        if service_area is not None:
            fields.append("service_area = ?")
            params.append(service_area)
        if accepted_food_types is not None:
            fields.append("accepted_food_types = ?")
            params.append(accepted_food_types)
        if capacity is not None:
            fields.append("capacity = ?")
            params.append(capacity)
        if availability is not None:
            fields.append("availability = ?")
            params.append(availability)
        if location is not None:
            fields.append("location = ?")
            params.append(location)

        if not fields:
            conn.close()
            return self.get_organization_record(org_id)

        params.append(org_id)
        query = f"UPDATE organizations SET {', '.join(fields)} WHERE id = ?"
        with conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM organizations WHERE id = ?", (org_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_volunteer_record(self, volunteer_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM volunteers WHERE id = ?", (volunteer_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_volunteer_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        if not phone:
            return None
        norm_digits = self._normalize_phone(phone)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM volunteers")
        rows = cursor.fetchall()
        conn.close()
        for row in rows:
            v = dict(row)
            v_digits = self._normalize_phone(v.get("phone", ""))
            if v_digits and norm_digits and (v_digits == norm_digits or v_digits.endswith(norm_digits) or norm_digits.endswith(v_digits)):
                return v
        return None

    def create_volunteer_record(
        self,
        volunteer_id: str,
        name: str,
        phone: str,
        service_area: str,
        transport_mode: str = "Motorbike",
        availability: str = "immediate, evenings",
        current_status: str = "available",
        location: Optional[str] = None
    ) -> Dict[str, Any]:
        conn = self._get_connection()
        now = self._now()
        loc = location or service_area.split(",")[0].strip()
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT OR REPLACE INTO volunteers (id, name, phone, service_area, transport_mode, availability, current_status, location, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (volunteer_id, name, phone, service_area, transport_mode, availability, current_status, loc, now))
        
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM volunteers WHERE id = ?", (volunteer_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}

    def update_volunteer_record(
        self,
        volunteer_id: str,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        service_area: Optional[str] = None,
        transport_mode: Optional[str] = None,
        availability: Optional[str] = None,
        current_status: Optional[str] = None,
        location: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if phone is not None:
            updates.append("phone = ?")
            params.append(self._normalize_phone(phone))
        if service_area is not None:
            updates.append("service_area = ?")
            params.append(service_area)
        if transport_mode is not None:
            updates.append("transport_mode = ?")
            params.append(transport_mode)
        if availability is not None:
            updates.append("availability = ?")
            params.append(availability)
        if current_status is not None:
            updates.append("current_status = ?")
            params.append(current_status)
        if location is not None:
            updates.append("location = ?")
            params.append(location)

        if not updates:
            conn.close()
            return self.get_volunteer_record(volunteer_id)

        params.append(volunteer_id)
        with conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE volunteers SET {', '.join(updates)} WHERE id = ?", tuple(params))

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM volunteers WHERE id = ?", (volunteer_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None


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
        conn = self._get_connection()
        now = self._now()
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO donations (id, donor_id, food_type, quantity, unit, dietary_information, pickup_location, available_from, pickup_deadline, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'AVAILABLE', ?, ?)
            ''', (donation_id, donor_id, food_type, quantity, unit, dietary_info, location, available_from, deadline, now, now))

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM donations WHERE id = ?", (donation_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}

    def get_donation_record(self, donation_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM donations WHERE id = ?", (donation_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_donation_status_record(self, donation_id: str, status: str) -> bool:
        conn = self._get_connection()
        now = self._now()
        with conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE donations SET status = ?, updated_at = ? WHERE id = ?", (status, now, donation_id))
            rows_affected = cursor.rowcount
        conn.close()
        return rows_affected > 0

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
        conn = self._get_connection()
        now = self._now()
        fields = []
        values = []
        if food_type is not None and str(food_type).strip():
            fields.append("food_type = ?")
            values.append(str(food_type).strip())
        if quantity is not None:
            fields.append("quantity = ?")
            values.append(float(quantity))
        if unit is not None and str(unit).strip():
            fields.append("unit = ?")
            values.append(str(unit).strip())
        if dietary_info is not None:
            fields.append("dietary_information = ?")
            values.append(str(dietary_info).strip())
        if location is not None and str(location).strip():
            fields.append("pickup_location = ?")
            values.append(str(location).strip())
        if available_from is not None and str(available_from).strip():
            fields.append("available_from = ?")
            values.append(str(available_from).strip())
        if deadline is not None and str(deadline).strip():
            fields.append("pickup_deadline = ?")
            values.append(str(deadline).strip())

        if not fields:
            conn.close()
            return self.get_donation_record(donation_id)

        fields.append("updated_at = ?")
        values.append(now)
        values.append(donation_id)

        with conn:
            cursor = conn.cursor()
            query = f"UPDATE donations SET {', '.join(fields)} WHERE id = ?"
            cursor.execute(query, tuple(values))
            rows_affected = cursor.rowcount

        if rows_affected > 0:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM donations WHERE id = ?", (donation_id,))
            row = cursor.fetchone()
            conn.close()
            return dict(row) if row else None

        conn.close()
        return None

    def find_organizations_by_criteria(self, food_type: str, location: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        loc_clean = location.strip().lower()
        food_clean = food_type.strip().lower()

        import routing
        target_district = (routing.resolve_district(location) or "").lower()

        cursor.execute("SELECT * FROM organizations")
        all_orgs = [dict(row) for row in cursor.fetchall()]
        conn.close()

        ranked_orgs = []
        for org in all_orgs:
            score = 0
            service_area = org.get("service_area", "").lower()
            org_location = org.get("location", "").lower()
            org_district = (routing.resolve_district(org.get("service_area") or org.get("location")) or "").lower()
            accepted_types = org.get("accepted_food_types", "").lower()

            # District matching boost
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
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM donations WHERE id = ?", (donation_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False

        now = self._now()
        with conn:
            cursor.execute("UPDATE donations SET status = 'MATCHED', updated_at = ? WHERE id = ?", (now, donation_id))
            rows_affected = cursor.rowcount
        conn.close()
        return rows_affected > 0

    def find_volunteers_by_criteria(self, location: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        loc_clean = location.strip().lower()

        import routing
        target_district = (routing.resolve_district(location) or "").lower()

        cursor.execute("SELECT * FROM volunteers WHERE current_status = 'available'")
        all_vols = [dict(row) for row in cursor.fetchall()]
        conn.close()

        matched_vols = []
        for vol in all_vols:
            score = 0
            service_area = vol.get("service_area", "").lower()
            vol_loc = vol.get("location", "").lower()
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

    def create_pickup_task_record(
        self,
        task_id: str,
        donation_id: str,
        org_id: str,
        pickup_loc: str,
        delivery_loc: str,
        time: str
    ) -> Dict[str, Any]:
        conn = self._get_connection()
        now = self._now()
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO pickup_tasks (id, donation_id, organization_id, volunteer_id, pickup_location, delivery_location, scheduled_time, status, created_at, updated_at)
            VALUES (?, ?, ?, NULL, ?, ?, ?, 'PENDING', ?, ?)
            ''', (task_id, donation_id, org_id, pickup_loc, delivery_loc, time, now, now))

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pickup_tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}

    def get_pickup_task_record(self, task_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pickup_tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_pickup_tasks_by_donation_id(self, donation_id: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pickup_tasks WHERE donation_id = ? ORDER BY created_at DESC", (donation_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_donations_by_donor_id(self, donor_id: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM donations WHERE donor_id = ? ORDER BY created_at DESC", (donor_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_pickup_tasks_for_volunteer(self, volunteer_id: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pickup_tasks WHERE volunteer_id = ? ORDER BY created_at DESC", (volunteer_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_pickup_tasks_for_organization(self, org_id: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pickup_tasks WHERE organization_id = ? ORDER BY created_at DESC", (org_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def assign_volunteer_record(self, task_id: str, volunteer_id: str, atomic_claim: bool = False) -> bool:
        conn = self._get_connection()
        now = self._now()
        with conn:
            cursor = conn.cursor()
            if atomic_claim:
                cursor.execute(
                    "UPDATE pickup_tasks SET volunteer_id = ?, status = 'ASSIGNED', updated_at = ? WHERE id = ? AND (status IN ('PENDING', 'OFFERED', 'OPEN') OR volunteer_id IS NULL OR volunteer_id = '')",
                    (volunteer_id, now, task_id)
                )
            else:
                cursor.execute("UPDATE pickup_tasks SET volunteer_id = ?, status = 'ASSIGNED', updated_at = ? WHERE id = ?", (volunteer_id, now, task_id))
            rows = cursor.rowcount
        conn.close()
        return rows > 0

    def update_pickup_status_record(self, task_id: str, status: str) -> bool:
        conn = self._get_connection()
        now = self._now()
        with conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE pickup_tasks SET status = ?, updated_at = ? WHERE id = ?", (status, now, task_id))
            rows = cursor.rowcount
        conn.close()
        return rows > 0

    def create_notification_record(
        self,
        notif_id: str,
        recipient_type: str,
        recipient_id: str,
        message: str,
        channel: str
    ) -> None:
        conn = self._get_connection()
        now = self._now()
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO notifications (id, recipient_type, recipient_id, message, channel, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'SENT', ?)
            ''', (notif_id, recipient_type, recipient_id, message, channel, now))
        conn.close()

    def get_notifications_for_recipient(self, recipient_id: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM notifications WHERE recipient_id = ? ORDER BY created_at DESC", (recipient_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_all_donations(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        if status and status.strip():
            cursor.execute("SELECT * FROM donations WHERE status = ? ORDER BY created_at DESC", (status.strip().upper(),))
        else:
            cursor.execute("SELECT * FROM donations ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_all_organizations(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM organizations ORDER BY name ASC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_all_volunteers(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM volunteers ORDER BY name ASC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_all_pickup_tasks(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT 
            p.*,
            o.name as organization_name,
            v.name as volunteer_name
        FROM pickup_tasks p
        LEFT JOIN organizations o ON p.organization_id = o.id
        LEFT JOIN volunteers v ON p.volunteer_id = v.id
        ORDER BY p.created_at DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_all_notifications(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_dashboard_stats(self) -> Dict[str, Any]:
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM donations")
        total_donations = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(quantity), 0) FROM donations")
        total_food_quantity = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM donations WHERE status = 'AVAILABLE'")
        available_donations = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM donations WHERE status IN ('MATCHED', 'PICKUP_PENDING', 'PICKUP_ASSIGNED', 'COLLECTED')")
        active_rescues = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM donations WHERE status = 'DELIVERED'")
        delivered_rescues = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM organizations")
        total_organizations = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM volunteers")
        total_volunteers = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM volunteers WHERE current_status = 'available'")
        available_volunteers = cursor.fetchone()[0]

        cursor.execute("SELECT status, COUNT(*) as count FROM donations GROUP BY status")
        status_distribution = {row["status"]: row["count"] for row in cursor.fetchall()}

        conn.close()
        return {
            "total_donations": total_donations,
            "total_food_quantity": round(float(total_food_quantity), 1),
            "available_donations": available_donations,
            "active_rescues": active_rescues,
            "delivered_rescues": delivered_rescues,
            "total_organizations": total_organizations,
            "total_volunteers": total_volunteers,
            "available_volunteers": available_volunteers,
            "status_distribution": status_distribution,
        }

    def reset_database_data(self, wipe_all: bool = False) -> None:
        self.setup_database()
        conn = self._get_connection()
        with conn:
            cursor = conn.cursor()
            tables = [
                "messages",
                "pickup_location_history",
                "reimbursements",
                "pickup_tasks",
                "notifications",
                "donations",
                "audit_events",
                "users"
            ]
            if wipe_all:
                tables.extend(["volunteers", "organizations", "donors"])
            for tbl in tables:
                try:
                    cursor.execute(f"DELETE FROM {tbl}")
                except sqlite3.OperationalError:
                    pass
            try:
                default_settings = json.dumps({
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
                })
                cursor.execute(
                    "INSERT INTO system_settings (setting_key, setting_value, updated_at) VALUES ('transport_cost', ?, ?) "
                    "ON CONFLICT(setting_key) DO UPDATE SET setting_value = ?, updated_at = ?",
                    (default_settings, self._now(), default_settings, self._now())
                )
            except Exception:
                pass
        conn.close()

    # Reimbursements (Accounting Ledger)
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
        conn = self._get_connection()
        now = self._now()
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO reimbursements (id, pickup_task_id, volunteer_id, distance_km, rate_per_km, transport_mode, amount, currency, status, created_at, approved_at, paid_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, NULL, NULL, ?)
            ''', (reimbursement_id, pickup_task_id, volunteer_id, float(distance_km), float(rate_per_km), str(transport_mode), float(amount), str(currency), now, notes))
        
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reimbursements WHERE id = ?", (reimbursement_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}

    def get_reimbursement_record(self, reimbursement_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reimbursements WHERE id = ?", (reimbursement_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_reimbursement_by_pickup_id(self, pickup_task_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reimbursements WHERE pickup_task_id = ? ORDER BY created_at DESC", (pickup_task_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_reimbursements_for_volunteer(self, volunteer_id: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reimbursements WHERE volunteer_id = ? ORDER BY created_at DESC", (volunteer_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_all_reimbursements(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        if status and status.strip():
            cursor.execute("""
            SELECT r.*, v.name as volunteer_name
            FROM reimbursements r
            LEFT JOIN volunteers v ON r.volunteer_id = v.id
            WHERE r.status = ?
            ORDER BY r.created_at DESC
            """, (status.strip().upper(),))
        else:
            cursor.execute("""
            SELECT r.*, v.name as volunteer_name
            FROM reimbursements r
            LEFT JOIN volunteers v ON r.volunteer_id = v.id
            ORDER BY r.created_at DESC
            """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_reimbursement_status_record(
        self,
        reimbursement_id: str,
        status: str,
        notes: Optional[str] = None
    ) -> bool:
        conn = self._get_connection()
        now = self._now()
        norm_status = str(status).strip().upper()
        approved_at = now if norm_status == "APPROVED" else None
        paid_at = now if norm_status == "PAID" else None

        with conn:
            cursor = conn.cursor()
            if approved_at:
                cursor.execute(
                    "UPDATE reimbursements SET status = ?, approved_at = ?, notes = COALESCE(?, notes) WHERE id = ?",
                    (norm_status, approved_at, notes, reimbursement_id)
                )
            elif paid_at:
                cursor.execute(
                    "UPDATE reimbursements SET status = ?, paid_at = ?, notes = COALESCE(?, notes) WHERE id = ?",
                    (norm_status, paid_at, notes, reimbursement_id)
                )
            else:
                cursor.execute(
                    "UPDATE reimbursements SET status = ?, notes = COALESCE(?, notes) WHERE id = ?",
                    (norm_status, notes, reimbursement_id)
                )
            rows = cursor.rowcount
        conn.close()
        return rows > 0

    # GPS Location History
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
        conn = self._get_connection()
        ts = timestamp or self._now()
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO pickup_location_history (id, pickup_task_id, volunteer_id, latitude, longitude, accuracy_m, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (location_id, pickup_task_id, volunteer_id, float(latitude), float(longitude), float(accuracy_m) if accuracy_m is not None else None, ts))
        
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pickup_location_history WHERE id = ?", (location_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}

    def get_latest_pickup_location(self, pickup_task_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pickup_location_history WHERE pickup_task_id = ? ORDER BY timestamp DESC LIMIT 1", (pickup_task_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_pickup_location_history(self, pickup_task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pickup_location_history WHERE pickup_task_id = ? ORDER BY timestamp DESC LIMIT ?", (pickup_task_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # Volunteer Availability & Location Coordination
    def update_volunteer_availability(
        self,
        volunteer_id: str,
        status: str,
        current_location: Optional[str] = None,
        current_coordinates: Optional[Dict[str, Any]] = None
    ) -> bool:
        conn = self._get_connection()
        norm_status = str(status).strip().upper()
        now = self._now()
        coords_json = json.dumps(current_coordinates) if current_coordinates else None
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE volunteers
            SET availability_status = ?,
                current_status = ?,
                current_location = COALESCE(?, current_location),
                current_coordinates = COALESCE(?, current_coordinates),
                last_available_at = CASE WHEN ? = 'AVAILABLE' THEN ? ELSE last_available_at END
            WHERE id = ?
            ''', (norm_status, norm_status.lower(), current_location, coords_json, norm_status, now, volunteer_id))
            rows = cursor.rowcount
        conn.close()
        return rows > 0

    def get_available_volunteers(
        self,
        service_area: Optional[str] = None,
        min_capacity: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM volunteers WHERE availability_status = 'AVAILABLE' OR current_status = 'available'")
        rows = cursor.fetchall()
        conn.close()
        
        vols = []
        for r in rows:
            v = dict(r)
            if v.get("current_coordinates"):
                try:
                    v["current_coordinates"] = json.loads(v["current_coordinates"])
                except Exception:
                    pass
            # Capacity check
            cap = int(v.get("vehicle_capacity", 25) or 25)
            if min_capacity and cap < min_capacity:
                continue
            # Service area match
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
        conn = self._get_connection()
        p_coords_json = json.dumps(pickup_coordinates) if pickup_coordinates else None
        d_coords_json = json.dumps(destination_coordinates) if destination_coordinates else None
        now = self._now()
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE pickup_tasks
            SET pickup_coordinates = COALESCE(?, pickup_coordinates),
                pickup_location_confirmed = CASE WHEN ? IS NOT NULL THEN 1 ELSE pickup_location_confirmed END,
                destination_coordinates = COALESCE(?, destination_coordinates),
                destination_location_confirmed = CASE WHEN ? IS NOT NULL THEN 1 ELSE destination_location_confirmed END,
                pickup_distance_km = COALESCE(?, pickup_distance_km),
                pickup_duration_minutes = COALESCE(?, pickup_duration_minutes),
                delivery_distance_km = COALESCE(?, delivery_distance_km),
                delivery_duration_minutes = COALESCE(?, delivery_duration_minutes),
                total_distance_km = COALESCE(?, total_distance_km),
                estimated_transport_cost = COALESCE(?, estimated_transport_cost),
                updated_at = ?
            WHERE id = ?
            ''', (
                p_coords_json, p_coords_json,
                d_coords_json, d_coords_json,
                pickup_distance_km, pickup_duration_minutes,
                delivery_distance_km, delivery_duration_minutes,
                total_distance_km, estimated_transport_cost,
                now, task_id
            ))
            rows = cursor.rowcount
        conn.close()
        return rows > 0

    # Audit Trail Event Logging
    def create_audit_event_record(
        self,
        event_id: str,
        event_type: str,
        actor: str,
        related_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        conn = self._get_connection()
        now = self._now()
        meta_json = json.dumps(metadata) if metadata else None
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO audit_events (id, event_type, actor, related_id, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (event_id, event_type, actor, related_id, meta_json, now))
        
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_events WHERE id = ?", (event_id,))
        row = cursor.fetchone()
        conn.close()
        res = dict(row) if row else {}
        if res.get("metadata"):
            try:
                res["metadata"] = json.loads(res["metadata"])
            except Exception:
                pass
        return res

    def get_audit_events_for_task(self, related_id: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_events WHERE related_id = ? ORDER BY created_at ASC", (related_id,))
        rows = cursor.fetchall()
        conn.close()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("metadata"):
                try:
                    d["metadata"] = json.loads(d["metadata"])
                except Exception:
                    pass
            results.append(d)
        return results

    # User Profile & Onboarding Management
    def get_user_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        norm = self._normalize_phone(phone)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE phone_number = ?", (norm,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        d["onboarding_completed"] = bool(d.get("onboarding_completed", 0))
        d["preferred_response_mode"] = d.get("preferred_response_mode") or "text"
        
        # Parse JSON columns safely
        for json_col in ["metadata", "conversation_state", "active_draft"]:
            if d.get(json_col):
                try:
                    d[json_col] = json.loads(d[json_col])
                except Exception:
                    pass
            elif json_col in ["conversation_state", "active_draft", "metadata"]:
                d[json_col] = {}

        # Enrich display_name and user_role from donor/volunteer/org records if fallback
        if not d.get("display_name") or d.get("display_name", "").startswith("User_") or d.get("user_role") in ["unknown", None, ""]:
            donor_rec = self.get_donor_by_phone(norm)
            if donor_rec and donor_rec.get("name"):
                d["display_name"] = donor_rec["name"]
                d["user_role"] = "donor"
            else:
                vol_rec = self.get_volunteer_by_phone(norm)
                if vol_rec and vol_rec.get("name"):
                    d["display_name"] = vol_rec["name"]
                    d["user_role"] = "volunteer"
                else:
                    org_rec = self.get_organization_by_phone(norm)
                    if org_rec and org_rec.get("name"):
                        d["display_name"] = org_rec["name"]
                        d["user_role"] = "organization"

        return d

    def create_or_update_user(
        self,
        phone: str,
        display_name: Optional[str] = None,
        preferred_language: str = "en",
        preferred_response_mode: str = "text",
        user_role: str = "unknown",
        onboarding_completed: bool = False,
        default_location: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        norm = self._normalize_phone(phone)
        conn = self._get_connection()
        now = self._now()
        meta_json = json.dumps(metadata) if metadata else None
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE phone_number = ?", (norm,))
            existing = cursor.fetchone()
            if existing:
                cursor.execute('''
                UPDATE users SET
                    display_name = COALESCE(?, display_name),
                    preferred_language = COALESCE(?, preferred_language),
                    preferred_response_mode = COALESCE(?, preferred_response_mode),
                    user_role = CASE WHEN ? != 'unknown' THEN ? ELSE user_role END,
                    onboarding_completed = CASE WHEN ? = 1 THEN 1 ELSE onboarding_completed END,
                    default_location = COALESCE(?, default_location),
                    last_seen_at = ?,
                    metadata = COALESCE(?, metadata)
                WHERE phone_number = ?
                ''', (
                    display_name,
                    preferred_language,
                    preferred_response_mode,
                    user_role, user_role,
                    1 if onboarding_completed else 0,
                    default_location,
                    now,
                    meta_json,
                    norm
                ))
            else:
                cursor.execute('''
                INSERT INTO users (phone_number, display_name, preferred_language, preferred_response_mode, user_role, onboarding_completed, default_location, first_seen_at, last_seen_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    norm,
                    display_name or f"User_{norm[-4:]}",
                    preferred_language or "en",
                    preferred_response_mode or "text",
                    user_role,
                    1 if onboarding_completed else 0,
                    default_location,
                    now,
                    now,
                    meta_json
                ))
        conn.close()
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
        conn = self._get_connection()
        now = self._now()
        meta_json = json.dumps(metadata) if metadata is not None else None
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE phone_number = ?", (norm,))
            existing = cursor.fetchone()
            if not existing:
                cursor.execute('''
                INSERT INTO users (phone_number, display_name, preferred_language, preferred_response_mode, user_role, default_location, active_donation_id, active_task_id, first_seen_at, last_seen_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    norm,
                    display_name or f"User_{norm[-4:]}",
                    preferred_language or "en",
                    preferred_response_mode or "text",
                    user_role or "unknown",
                    default_location,
                    active_donation_id,
                    active_task_id,
                    now,
                    now,
                    meta_json
                ))
            else:
                cursor.execute('''
                UPDATE users SET
                    display_name = COALESCE(?, display_name),
                    preferred_language = COALESCE(?, preferred_language),
                    preferred_response_mode = COALESCE(?, preferred_response_mode),
                    user_role = COALESCE(?, user_role),
                    default_location = COALESCE(?, default_location),
                    active_donation_id = COALESCE(?, active_donation_id),
                    active_task_id = COALESCE(?, active_task_id),
                    metadata = COALESCE(?, metadata),
                    last_seen_at = ?
                WHERE phone_number = ?
                ''', (
                    display_name,
                    preferred_language,
                    preferred_response_mode,
                    user_role,
                    default_location,
                    active_donation_id,
                    active_task_id,
                    meta_json,
                    now,
                    norm
                ))
        conn.close()
        return self.get_user_by_phone(norm) or {}

    def set_user_language(self, phone: str, language: str) -> bool:
        norm = self._normalize_phone(phone)
        conn = self._get_connection()
        now = self._now()
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT phone_number FROM users WHERE phone_number = ?", (norm,))
            if not cursor.fetchone():
                cursor.execute('''
                INSERT INTO users (phone_number, display_name, preferred_language, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                ''', (norm, f"User_{norm[-4:]}", language.lower().strip(), now, now))
                updated = True
            else:
                cursor.execute('''
                UPDATE users SET preferred_language = ?, last_seen_at = ? WHERE phone_number = ?
                ''', (language.lower().strip(), now, norm))
                updated = cursor.rowcount > 0
        conn.close()
        return updated

    def set_user_response_mode(self, phone: str, mode: str) -> bool:
        norm = self._normalize_phone(phone)
        conn = self._get_connection()
        now = self._now()
        clean_mode = "voice" if "voice" in mode.lower() else "text"
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT phone_number FROM users WHERE phone_number = ?", (norm,))
            if not cursor.fetchone():
                cursor.execute('''
                INSERT INTO users (phone_number, display_name, preferred_response_mode, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                ''', (norm, f"User_{norm[-4:]}", clean_mode, now, now))
                updated = True
            else:
                cursor.execute('''
                UPDATE users SET preferred_response_mode = ?, last_seen_at = ? WHERE phone_number = ?
                ''', (clean_mode, now, norm))
                updated = cursor.rowcount > 0
        conn.close()
        return updated

    def set_onboarding_completed(self, phone: str, completed: bool = True) -> bool:
        norm = self._normalize_phone(phone)
        conn = self._get_connection()
        now = self._now()
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE users SET onboarding_completed = ?, last_seen_at = ? WHERE phone_number = ?
            ''', (1 if completed else 0, now, norm))
            updated = cursor.rowcount > 0
        conn.close()
        return updated

    def get_user_conversation_state(self, phone: str) -> Dict[str, Any]:
        user = self.get_user_by_phone(phone)
        if user and isinstance(user.get("conversation_state"), dict):
            return user["conversation_state"]
        return {}

    def set_user_conversation_state(self, phone: str, state: Dict[str, Any]) -> bool:
        norm = self._normalize_phone(phone)
        conn = self._get_connection()
        now = self._now()
        state_json = json.dumps(state) if state else None
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT phone_number FROM users WHERE phone_number = ?", (norm,))
            if not cursor.fetchone():
                cursor.execute('''
                INSERT INTO users (phone_number, display_name, conversation_state, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                ''', (norm, f"User_{norm[-4:]}", state_json, now, now))
                updated = True
            else:
                cursor.execute('''
                UPDATE users SET conversation_state = ?, last_seen_at = ? WHERE phone_number = ?
                ''', (state_json, now, norm))
                updated = cursor.rowcount > 0
        conn.close()
        return updated

    def clear_user_conversation_state(self, phone: str) -> bool:
        return self.set_user_conversation_state(phone, {})

    def save_draft_donation(self, phone: str, draft_data: Dict[str, Any]) -> Dict[str, Any]:
        norm = self._normalize_phone(phone)
        user = self.get_user_by_phone(norm)
        existing_draft = (user.get("active_draft") or {}) if user else {}
        if not isinstance(existing_draft, dict):
            existing_draft = {}
        # Merge new draft data
        merged = dict(existing_draft)
        for k, v in draft_data.items():
            if v is not None:
                merged[k] = v

        conn = self._get_connection()
        now = self._now()
        draft_json = json.dumps(merged)
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT phone_number FROM users WHERE phone_number = ?", (norm,))
            if not cursor.fetchone():
                cursor.execute('''
                INSERT INTO users (phone_number, display_name, active_draft, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                ''', (norm, f"User_{norm[-4:]}", draft_json, now, now))
            else:
                cursor.execute('''
                UPDATE users SET active_draft = ?, last_seen_at = ? WHERE phone_number = ?
                ''', (draft_json, now, norm))
        conn.close()
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
        conn = self._get_connection()
        now = self._now()
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE users SET active_draft = NULL, last_seen_at = ? WHERE phone_number = ?
            ''', (now, norm))
            updated = cursor.rowcount > 0
        conn.close()
        return updated

    def get_all_users(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users ORDER BY last_seen_at DESC")
        rows = cursor.fetchall()
        conn.close()
        users = []
        for r in rows:
            d = dict(r)
            d["onboarding_completed"] = bool(d.get("onboarding_completed", 0))
            d["preferred_response_mode"] = d.get("preferred_response_mode") or "text"
            for json_col in ["metadata", "conversation_state", "active_draft"]:
                if d.get(json_col):
                    try:
                        d[json_col] = json.loads(d[json_col])
                    except Exception:
                        d[json_col] = {}
                else:
                    d[json_col] = {}
            users.append(d)
        return users

    def get_all_donors(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM donors ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def record_message(
        self,
        phone: str,
        sender: str,
        text: str,
        is_voice: bool = False,
        transcript: Optional[str] = None,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        import uuid
        norm = self._normalize_phone(phone)
        msg_id = f"msg-{uuid.uuid4().hex[:8]}"
        ts = timestamp or self._now()
        conn = self._get_connection()
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO messages (id, phone_number, sender, message_text, is_voice, transcript, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (msg_id, norm, sender, text, 1 if is_voice else 0, transcript, ts))
            # Also ensure user record exists and update last_seen_at
            cursor.execute("SELECT phone_number FROM users WHERE phone_number = ?", (norm,))
            resp_mode = "voice" if is_voice else "text"
            if not cursor.fetchone():
                cursor.execute('''
                INSERT INTO users (phone_number, display_name, preferred_language, preferred_response_mode, first_seen_at, last_seen_at)
                VALUES (?, ?, 'en', ?, ?, ?)
                ''', (norm, f"User_{norm[-4:]}", resp_mode, ts, ts))
            else:
                cursor.execute("UPDATE users SET last_seen_at = ? WHERE phone_number = ?", (ts, norm))
        conn.close()
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
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
        SELECT 
            m.phone_number,
            COUNT(m.id) as message_count,
            MAX(m.timestamp) as last_activity
        FROM messages m
        GROUP BY m.phone_number
        ORDER BY last_activity DESC
        ''')
        rows = cursor.fetchall()
        conv_phones = {r["phone_number"]: dict(r) for r in rows}

        # Also pull all users even if they haven't sent a message yet
        cursor.execute("SELECT * FROM users ORDER BY last_seen_at DESC")
        user_rows = cursor.fetchall()
        conn.close()

        conversations = []
        seen_phones = set()

        for u_row in user_rows:
            u = dict(u_row)
            norm = u["phone_number"]
            seen_phones.add(norm)
            
            # Fetch latest message
            latest_msg = None
            msg_count = 0
            if norm in conv_phones:
                msg_count = conv_phones[norm]["message_count"]
                conn_sub = self._get_connection()
                cur_sub = conn_sub.cursor()
                cur_sub.execute("SELECT * FROM messages WHERE phone_number = ? ORDER BY timestamp DESC LIMIT 1", (norm,))
                last_m = cur_sub.fetchone()
                conn_sub.close()
                if last_m:
                    latest_msg = dict(last_m)

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
                "last_message_is_voice": bool(latest_msg.get("is_voice", 0)) if latest_msg else False,
                "last_activity": latest_msg.get("timestamp") if latest_msg else u.get("last_seen_at", self._now()),
                "onboarding_completed": bool(u.get("onboarding_completed", 0)),
            })

        return conversations

    def get_conversation_messages(self, phone: str, limit: int = 100) -> List[Dict[str, Any]]:
        norm = self._normalize_phone(phone)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE phone_number = ? ORDER BY timestamp ASC LIMIT ?", (norm, limit))
        rows = cursor.fetchall()
        conn.close()
        msgs = []
        for r in rows:
            d = dict(r)
            d["is_voice"] = bool(d.get("is_voice", 0))
            msgs.append(d)
        return msgs

    def get_all_audit_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        events = []
        for r in rows:
            d = dict(r)
            if d.get("metadata"):
                try:
                    d["metadata"] = json.loads(d["metadata"])
                except Exception:
                    pass
            events.append(d)
        return events

    def get_transport_settings(self) -> Dict[str, Any]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT setting_value FROM system_settings WHERE setting_key = 'transport_cost'")
        row = cursor.fetchone()
        conn.close()
        if row and row["setting_value"]:
            try:
                data = json.loads(row["setting_value"])
                if "rates_by_vehicle" not in data:
                    data["rates_by_vehicle"] = {
                        "Motorbike": 50.0,
                        "Three-Wheeler": 90.0,
                        "Car": 80.0,
                        "Van": 120.0,
                        "Bicycle": 25.0,
                        "Electric Bike": 25.0
                    }
                return data
            except Exception:
                pass
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
        conn = self._get_connection()
        now = self._now()
        val_json = json.dumps(settings)
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO system_settings (setting_key, setting_value, updated_at)
            VALUES ('transport_cost', ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET setting_value = ?, updated_at = ?
            ''', (val_json, now, val_json, now))
        conn.close()
        return settings


