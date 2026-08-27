-- FoodRescue AI Supabase PostgreSQL Schema Migration
-- Migration: 20260827000000_create_foodrescue_schema.sql
-- Description: Complete schema for donors, organizations, volunteers, donations,
--              pickup tasks, notifications, audit events, reimbursements,
--              pickup location history, users, messages, settings, and QR codes.

-- Enable UUID extension if available
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Donors Table
CREATE TABLE IF NOT EXISTS donors (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(64),
    organization_name VARCHAR(255),
    location TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_donors_phone ON donors (phone);
CREATE INDEX IF NOT EXISTS idx_donors_created_at ON donors (created_at DESC);

-- 2. Recipient Organizations Table
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
);

CREATE INDEX IF NOT EXISTS idx_organizations_phone ON organizations (phone);
CREATE INDEX IF NOT EXISTS idx_organizations_service_area ON organizations (service_area);
CREATE INDEX IF NOT EXISTS idx_organizations_location ON organizations (location);

-- 3. Volunteers / Couriers Table
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
    current_coordinates JSONB,
    vehicle_capacity INTEGER DEFAULT 25,
    completed_pickups INTEGER DEFAULT 0,
    last_available_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_volunteers_phone ON volunteers (phone);
CREATE INDEX IF NOT EXISTS idx_volunteers_current_status ON volunteers (current_status);
CREATE INDEX IF NOT EXISTS idx_volunteers_availability_status ON volunteers (availability_status);
CREATE INDEX IF NOT EXISTS idx_volunteers_service_area ON volunteers (service_area);

-- 4. Food Donations Table
CREATE TABLE IF NOT EXISTS donations (
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

CREATE INDEX IF NOT EXISTS idx_donations_donor_id ON donations (donor_id);
CREATE INDEX IF NOT EXISTS idx_donations_status ON donations (status);
CREATE INDEX IF NOT EXISTS idx_donations_pickup_location ON donations (pickup_location);
CREATE INDEX IF NOT EXISTS idx_donations_created_at ON donations (created_at DESC);

-- 5. Pickup & Delivery Tasks Table
CREATE TABLE IF NOT EXISTS pickup_tasks (
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

CREATE INDEX IF NOT EXISTS idx_pickup_tasks_donation_id ON pickup_tasks (donation_id);
CREATE INDEX IF NOT EXISTS idx_pickup_tasks_org_id ON pickup_tasks (organization_id);
CREATE INDEX IF NOT EXISTS idx_pickup_tasks_vol_id ON pickup_tasks (volunteer_id);
CREATE INDEX IF NOT EXISTS idx_pickup_tasks_status ON pickup_tasks (status);
CREATE INDEX IF NOT EXISTS idx_pickup_tasks_delivery_status ON pickup_tasks (delivery_status);
CREATE INDEX IF NOT EXISTS idx_pickup_tasks_created_at ON pickup_tasks (created_at DESC);

-- 6. Notifications Table
CREATE TABLE IF NOT EXISTS notifications (
    id VARCHAR(64) PRIMARY KEY,
    recipient_type VARCHAR(64) NOT NULL,
    recipient_id VARCHAR(64) NOT NULL,
    message TEXT NOT NULL,
    channel VARCHAR(64) NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'SENT',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_recipient_id ON notifications (recipient_id);
CREATE INDEX IF NOT EXISTS idx_notifications_recipient_type ON notifications (recipient_type);
CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications (created_at DESC);

-- 7. Audit Events Table
CREATE TABLE IF NOT EXISTS audit_events (
    id VARCHAR(64) PRIMARY KEY,
    event_type VARCHAR(128) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    related_id VARCHAR(64),
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_related_id ON audit_events (related_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_event_type ON audit_events (event_type);
CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events (created_at DESC);

-- 8. Reimbursements Table
CREATE TABLE IF NOT EXISTS reimbursements (
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

CREATE INDEX IF NOT EXISTS idx_reimbursements_pickup_task_id ON reimbursements (pickup_task_id);
CREATE INDEX IF NOT EXISTS idx_reimbursements_volunteer_id ON reimbursements (volunteer_id);
CREATE INDEX IF NOT EXISTS idx_reimbursements_status ON reimbursements (status);
CREATE INDEX IF NOT EXISTS idx_reimbursements_created_at ON reimbursements (created_at DESC);

-- 9. Pickup Location History Table (GPS Breadcrumbs)
CREATE TABLE IF NOT EXISTS pickup_location_history (
    id VARCHAR(64) PRIMARY KEY,
    pickup_task_id VARCHAR(64) NOT NULL REFERENCES pickup_tasks(id) ON DELETE CASCADE,
    volunteer_id VARCHAR(64) NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
    latitude NUMERIC(10, 7) NOT NULL,
    longitude NUMERIC(10, 7) NOT NULL,
    accuracy_m NUMERIC(10, 2),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_location_history_task_id ON pickup_location_history (pickup_task_id);
CREATE INDEX IF NOT EXISTS idx_location_history_volunteer_id ON pickup_location_history (volunteer_id);
CREATE INDEX IF NOT EXISTS idx_location_history_timestamp ON pickup_location_history (timestamp DESC);

-- 10. Persistent Users & Profiles Table
CREATE TABLE IF NOT EXISTS users (
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

CREATE INDEX IF NOT EXISTS idx_users_user_role ON users (user_role);
CREATE INDEX IF NOT EXISTS idx_users_last_seen_at ON users (last_seen_at DESC);

-- 11. WhatsApp & Web Messages Table
CREATE TABLE IF NOT EXISTS messages (
    id VARCHAR(64) PRIMARY KEY,
    phone_number VARCHAR(64) NOT NULL,
    sender VARCHAR(64) NOT NULL,
    message_text TEXT NOT NULL,
    is_voice BOOLEAN DEFAULT FALSE,
    transcript TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_phone_number ON messages (phone_number);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages (timestamp ASC);

-- 12. System Settings Table
CREATE TABLE IF NOT EXISTS system_settings (
    setting_key VARCHAR(128) PRIMARY KEY,
    setting_value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 13. Physical Handover QR Codes Table
CREATE TABLE IF NOT EXISTS qr_codes (
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

CREATE INDEX IF NOT EXISTS idx_qr_codes_token ON qr_codes (token);
CREATE INDEX IF NOT EXISTS idx_qr_codes_task_id ON qr_codes (task_id);
CREATE INDEX IF NOT EXISTS idx_qr_codes_donation_id ON qr_codes (donation_id);
CREATE INDEX IF NOT EXISTS idx_qr_codes_status ON qr_codes (status);
CREATE INDEX IF NOT EXISTS idx_qr_codes_created_at ON qr_codes (created_at DESC);
