"""Capa de persistencia SQLite: esquema completo y conexion unica.

`_init_database()` crea las ~65 tablas y las migra (columnas nuevas con ALTER
idempotente). `_get_db_connection()` da la conexion, con `row_factory=Row` y
timeout de 10 s. Las DBs de captacion (outreach / instagram / tiktok / whatsapp)
NO pasan por aqui: cada una vive en su dominio con su propio fichero.

Que tabla guarda que:

| Dominio | Tablas |
| --- | --- |
| Clientes y acceso | `clientes`, `users`, `auth_sessions`, `password_reset_tokens`, `user_permission_overrides`, `admin_impersonations`, `system_settings` |
| Agenda | `bookings`, `booking_audit`, `employees`, `agenda_blocks`, `locations`, `resources` |
| Catalogo | `services`, `service_location_overrides`, `service_payment_policies` |
| Conversaciones | `chat_sessions`, `chat_messages`, `chat_takeovers`, `live_chat_sessions`, `whatsapp_inbound_messages`, `voice_calls` |
| Cerebro | `kb_documents`, `kb_qa`, `keyword_rules` |
| Cobro de la cita | `booking_payments`, `cancellation_policies` |
| Mostrador y tienda | `products`, `product_sales`, `packages`, `package_purchases`, `gift_cards`, `gift_card_transactions`, `customer_payments`, `customer_payment_events` |
| Stripe del negocio | `client_payment_accounts`, `stripe_connected_accounts` |
| Nuestro cobro al negocio | `subscriptions`, `message_usage_events` |
| Canales de envio | `client_channel_settings`, `client_oauth_connections`, `client_channel_oauth_states`, `client_channel_audit`, `client_channel_requests`, `gmail_connections`, `gmail_oauth_states`, `oauth_states` |
| WhatsApp propio | `client_whatsapp_accounts`, `wa_demo_codes`, `wa_demo_routes` |
| CRM | `crm_contacts`, `crm_contact_links`, `crm_contact_audit` |
| Demos y leads | `demo_tenants_registry`, `demo_registry_meta`, `demo_tenant_cleanup_queue`, `bot_leads`, `consulta_leads` |
| Metricas | `analytics_events`, `ai_rebooking_log`, `growth_daily`, `growth_opportunities`, `growth_opportunity_audit`, `growth_plan_tasks`, `growth_weekly_reviews` |

Ojo con los DOS sitios donde vive el dinero de una cita: `booking_payments` (la
señal / el pago de la reserva) y `customer_payments` con `kind='pos'` (lo que se
cobra en el mostrador). Consultar solo uno hace que el saldo mienta; la verdad
unificada la da `backend/paystate.py`.

Para anadir una columna: se declara en el CREATE TABLE **y** se anade su ALTER en
la seccion de migraciones, o las instalaciones existentes no la tendran.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
from typing import Optional

from fastapi import HTTPException

from backend import settings, timeutils

def _ensure_runtime_directories() -> None:
    settings.STORAGE_DIR.mkdir(exist_ok=True)
    settings.UPLOADS_DIR.mkdir(exist_ok=True)
    settings.WIDGET_DIR.mkdir(exist_ok=True)
    settings.ADMIN_UI_DIR.mkdir(exist_ok=True)
    settings.ACCESS_UI_DIR.mkdir(exist_ok=True)
    settings.ONBOARDING_UI_DIR.mkdir(exist_ok=True)
    settings.APP_UI_DIR.mkdir(exist_ok=True)


def _init_database() -> None:
    _ensure_runtime_directories()
    with _get_db_connection() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                employee_id TEXT NOT NULL DEFAULT '',
                employee_name TEXT NOT NULL DEFAULT '',
                nombre TEXT NOT NULL,
                email TEXT NOT NULL,
                telefono TEXT,
                servicio TEXT,
                booking_date TEXT NOT NULL,
                booking_time TEXT NOT NULL,
                notas TEXT,
                status TEXT NOT NULL,
                provider_name TEXT NOT NULL DEFAULT 'internal',
                provider_status TEXT NOT NULL,
                provider_booking_id TEXT NOT NULL DEFAULT '',
                provider_booking_url TEXT NOT NULL DEFAULT '',
                manage_token TEXT NOT NULL DEFAULT '',
                timezone TEXT NOT NULL DEFAULT '',
                start_at TEXT NOT NULL DEFAULT '',
                end_at TEXT NOT NULL DEFAULT '',
                confirmed_at TEXT NOT NULL DEFAULT '',
                cancelled_at TEXT NOT NULL DEFAULT '',
                rescheduled_at TEXT NOT NULL DEFAULT '',
                rescheduled_from_booking_id TEXT NOT NULL DEFAULT '',
                confirmation_email_sent_at TEXT NOT NULL DEFAULT '',
                reminder_24h_sent_at TEXT NOT NULL DEFAULT '',
                reminder_2h_sent_at TEXT NOT NULL DEFAULT '',
                review_request_sent_at TEXT NOT NULL DEFAULT '',
                customer_email_status TEXT NOT NULL DEFAULT '',
                customer_email_last_error TEXT NOT NULL DEFAULT '',
                booking_code TEXT NOT NULL DEFAULT '',
                completed_source TEXT NOT NULL DEFAULT '',
                service_id TEXT NOT NULL DEFAULT '',
                service_price_cents INTEGER NOT NULL DEFAULT 0,
                payment_status TEXT NOT NULL DEFAULT 'not_required',
                location_id TEXT NOT NULL DEFAULT '',
                resource_id TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(bookings)").fetchall()
        }
        if "provider_name" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN provider_name TEXT NOT NULL DEFAULT 'internal'"
            )
        if "employee_id" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN employee_id TEXT NOT NULL DEFAULT ''")
        if "employee_name" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN employee_name TEXT NOT NULL DEFAULT ''")
        if "provider_booking_id" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN provider_booking_id TEXT NOT NULL DEFAULT ''"
            )
        if "provider_booking_url" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN provider_booking_url TEXT NOT NULL DEFAULT ''"
            )
        if "manage_token" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN manage_token TEXT NOT NULL DEFAULT ''")
        if "timezone" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN timezone TEXT NOT NULL DEFAULT ''")
        if "start_at" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN start_at TEXT NOT NULL DEFAULT ''")
        if "end_at" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN end_at TEXT NOT NULL DEFAULT ''")
        if "confirmed_at" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN confirmed_at TEXT NOT NULL DEFAULT ''")
        if "cancelled_at" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN cancelled_at TEXT NOT NULL DEFAULT ''")
        if "rescheduled_at" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN rescheduled_at TEXT NOT NULL DEFAULT ''")
        if "rescheduled_from_booking_id" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN rescheduled_from_booking_id TEXT NOT NULL DEFAULT ''"
            )
        if "confirmation_email_sent_at" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN confirmation_email_sent_at TEXT NOT NULL DEFAULT ''"
            )
        if "reminder_24h_sent_at" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN reminder_24h_sent_at TEXT NOT NULL DEFAULT ''"
            )
        if "reminder_2h_sent_at" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN reminder_2h_sent_at TEXT NOT NULL DEFAULT ''"
            )
        if "review_request_sent_at" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN review_request_sent_at TEXT NOT NULL DEFAULT ''"
            )
        if "customer_email_status" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN customer_email_status TEXT NOT NULL DEFAULT ''"
            )
        if "customer_email_last_error" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN customer_email_last_error TEXT NOT NULL DEFAULT ''"
            )
        if "booking_code" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN booking_code TEXT NOT NULL DEFAULT ''")
        if "completed_source" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN completed_source TEXT NOT NULL DEFAULT ''")
        if "service_id" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN service_id TEXT NOT NULL DEFAULT ''")
        if "service_price_cents" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN service_price_cents INTEGER NOT NULL DEFAULT 0")
        if "payment_status" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'not_required'")
        if "location_id" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN location_id TEXT NOT NULL DEFAULT ''")
        if "resource_id" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN resource_id TEXT NOT NULL DEFAULT ''")
        # Copia de los tramos activo/espera del servicio EN EL MOMENTO de reservar.
        # Se guarda en la cita y no se relee del catalogo: si el negocio cambia el
        # servicio despues, la agenda de las citas ya cogidas no se descoloca.
        if "gap_json" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN gap_json TEXT NOT NULL DEFAULT ''")
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bookings_lookup
            ON bookings(cliente_id, employee_id, booking_date, booking_time, status)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_code
            ON bookings(cliente_id, booking_code)
            WHERE booking_code <> ''
            """
        )
        connection.execute("DROP INDEX IF EXISTS idx_bookings_unique_slot")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_unique_slot
            ON bookings(cliente_id, employee_id, booking_date, booking_time)
            WHERE status IN ('confirmed', 'pending_review', 'pending_payment')
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS employees (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                name TEXT NOT NULL,
                role_label TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '#00b1d9',
                is_active INTEGER NOT NULL DEFAULT 1,
                is_default INTEGER NOT NULL DEFAULT 0,
                timezone TEXT NOT NULL DEFAULT '',
                slot_minutes INTEGER NOT NULL DEFAULT 30,
                day_start TEXT NOT NULL DEFAULT '09:00',
                day_end TEXT NOT NULL DEFAULT '18:00',
                break_start TEXT NOT NULL DEFAULT '',
                break_end TEXT NOT NULL DEFAULT '',
                break_windows_json TEXT NOT NULL DEFAULT '[]',
                closed_weekdays_json TEXT NOT NULL DEFAULT '[]',
                service_ids_json TEXT NOT NULL DEFAULT '[]',
                location_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_employees_lookup
            ON employees(cliente_id, is_active, name)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_employees_default
            ON employees(cliente_id, is_default)
            WHERE is_default = 1
            """
        )
        employee_columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(employees)").fetchall()
        }
        if "service_ids_json" not in employee_columns:
            connection.execute("ALTER TABLE employees ADD COLUMN service_ids_json TEXT NOT NULL DEFAULT '[]'")
        if "break_start" not in employee_columns:
            connection.execute("ALTER TABLE employees ADD COLUMN break_start TEXT NOT NULL DEFAULT ''")
        if "break_end" not in employee_columns:
            connection.execute("ALTER TABLE employees ADD COLUMN break_end TEXT NOT NULL DEFAULT ''")
        if "break_windows_json" not in employee_columns:
            connection.execute("ALTER TABLE employees ADD COLUMN break_windows_json TEXT NOT NULL DEFAULT '[]'")
        if "location_id" not in employee_columns:
            connection.execute("ALTER TABLE employees ADD COLUMN location_id TEXT NOT NULL DEFAULT ''")
        if "weekly_hours_json" not in employee_columns:
            connection.execute("ALTER TABLE employees ADD COLUMN weekly_hours_json TEXT NOT NULL DEFAULT '{}'")
        # Orden en el que el negocio quiere ver a su equipo (y en el que lo ve el
        # cliente al elegir profesional). Con todos a 0 el orden sigue siendo el
        # alfabetico de siempre, asi que ningun tenant existente cambia.
        if "sort_order" not in employee_columns:
            connection.execute("ALTER TABLE employees ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_employees_location
            ON employees(cliente_id, location_id, is_active)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS booking_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id TEXT NOT NULL,
                cliente_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_booking_audit_lookup
            ON booking_audit(booking_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agenda_blocks (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                employee_id TEXT NOT NULL DEFAULT '',
                location_id TEXT NOT NULL DEFAULT '',
                block_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agenda_blocks_lookup
            ON agenda_blocks(cliente_id, employee_id, block_date, start_time)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS services (
                cliente_id TEXT NOT NULL,
                slug TEXT NOT NULL,
                name TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL DEFAULT 30,
                price_cents INTEGER NOT NULL DEFAULT 0,
                description TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                payment_mode TEXT NOT NULL DEFAULT 'payment_disabled',
                payment_type TEXT NOT NULL DEFAULT 'full',
                deposit_amount_cents INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'eur',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (cliente_id, slug)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_services_lookup
            ON services(cliente_id, is_active, sort_order, name)
            """
        )
        service_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(services)").fetchall()
        }
        for column_name, definition in {
            "payment_mode": "TEXT NOT NULL DEFAULT 'payment_disabled'",
            "payment_type": "TEXT NOT NULL DEFAULT 'full'",
            "deposit_amount_cents": "INTEGER NOT NULL DEFAULT 0",
            "currency": "TEXT NOT NULL DEFAULT 'eur'",
            # Override de politica de cancelacion por servicio (NULL = hereda del tenant).
            "cancel_free_hours": "INTEGER",
            "cancel_late_fee_pct": "INTEGER",
            "no_show_fee_pct": "INTEGER",
            # Imagen del servicio (URL configurable; se muestra en la central publica).
            "image_url": "TEXT NOT NULL DEFAULT ''",
            # Categoria del servicio (Peinados, Cortes, Color...). Vacia = sin agrupar.
            # Un salon con 190 servicios no cabe en una lista: se elige categoria antes.
            "category": "TEXT NOT NULL DEFAULT ''",
            # Que contarle al cliente al confirmar una cita de ESTE servicio (como venir
            # preparado, que traer). El mensaje de confirmacion del negocio es uno para
            # todos; esto es lo que cambia de un servicio a otro.
            "booking_note": "TEXT NOT NULL DEFAULT ''",
            # Tramos de trabajo y espera: [{"activo": 105, "espera": 90}, ...].
            # Un alisado o unas mechas dejan a la profesional LIBRE mientras actua
            # el producto, y en ese rato puede atender a otra clienta. Vacio (el
            # default) = el servicio ocupa su duracion entera, como siempre.
            "gap_json": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column_name not in service_columns:
                connection.execute(f"ALTER TABLE services ADD COLUMN {column_name} {definition}")
        # Politica de cancelacion/no-show por tenant (generica, opt-in).
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cancellation_policies (
                cliente_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                free_cancel_hours INTEGER NOT NULL DEFAULT 24,
                late_cancel_fee_pct INTEGER NOT NULL DEFAULT 0,
                no_show_fee_pct INTEGER NOT NULL DEFAULT 100,
                auto_apply INTEGER NOT NULL DEFAULT 1,
                policy_text TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        # Permisos granulares por usuario (override sobre el default del rol).
        # allowed: 1 = concedido, 0 = denegado. Sin fila = hereda el rol.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_permission_overrides (
                user_id TEXT NOT NULL,
                cliente_id TEXT NOT NULL,
                permission_key TEXT NOT NULL,
                allowed INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (user_id, permission_key)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_perm_overrides ON user_permission_overrides(user_id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS locations (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                name TEXT NOT NULL,
                address TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                timezone TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                is_default INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                whatsapp_phone_number_id TEXT NOT NULL DEFAULT '',
                voice_phone_number TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_locations_lookup
            ON locations(cliente_id, is_active, sort_order, name)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_locations_default
            ON locations(cliente_id, is_default)
            WHERE is_default = 1
            """
        )
        location_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(locations)").fetchall()
        }
        if "whatsapp_phone_number_id" not in location_columns:
            connection.execute(
                "ALTER TABLE locations ADD COLUMN whatsapp_phone_number_id TEXT NOT NULL DEFAULT ''"
            )
        if "voice_phone_number" not in location_columns:
            connection.execute(
                "ALTER TABLE locations ADD COLUMN voice_phone_number TEXT NOT NULL DEFAULT ''"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS service_location_overrides (
                cliente_id TEXT NOT NULL,
                service_slug TEXT NOT NULL,
                location_id TEXT NOT NULL,
                is_available INTEGER NOT NULL DEFAULT 1,
                price_cents INTEGER,
                duration_minutes INTEGER,
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (cliente_id, service_slug, location_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS resources (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                location_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_resources_lookup
            ON resources(cliente_id, location_id, is_active, sort_order)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                cliente_id TEXT NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                price_cents INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'eur',
                stock INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (cliente_id, id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS product_sales (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                location_id TEXT NOT NULL DEFAULT '',
                product_id TEXT NOT NULL,
                product_name TEXT NOT NULL DEFAULT '',
                qty INTEGER NOT NULL DEFAULT 1,
                unit_price_cents INTEGER NOT NULL DEFAULT 0,
                total_cents INTEGER NOT NULL DEFAULT 0,
                booking_id TEXT NOT NULL DEFAULT '',
                customer_name TEXT NOT NULL DEFAULT '',
                customer_email TEXT NOT NULL DEFAULT '',
                payment_method TEXT NOT NULL DEFAULT 'cash',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_product_sales_lookup
            ON product_sales(cliente_id, location_id, created_at)
            """
        )
        # Venta de producto con cobro online (Stripe): status + enlace al pago.
        product_sales_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(product_sales)").fetchall()
        }
        for column_name, definition in {
            "status": "TEXT NOT NULL DEFAULT 'paid'",
            "customer_payment_id": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column_name not in product_sales_columns:
                connection.execute(f"ALTER TABLE product_sales ADD COLUMN {column_name} {definition}")
        # Imagen de producto (URL configurable; tienda online + mostrador).
        product_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(products)").fetchall()
        }
        if "image_url" not in product_columns:
            connection.execute("ALTER TABLE products ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS packages (
                cliente_id TEXT NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                items_json TEXT NOT NULL DEFAULT '[]',
                price_cents INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'eur',
                validity_days INTEGER NOT NULL DEFAULT 365,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (cliente_id, id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS package_purchases (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                package_id TEXT NOT NULL,
                package_name TEXT NOT NULL DEFAULT '',
                buyer_name TEXT NOT NULL DEFAULT '',
                buyer_email TEXT NOT NULL DEFAULT '',
                buyer_phone TEXT NOT NULL DEFAULT '',
                price_cents INTEGER NOT NULL DEFAULT 0,
                remaining_json TEXT NOT NULL DEFAULT '{}',
                expires_at TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                payment_method TEXT NOT NULL DEFAULT 'cash',
                location_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_package_purchases_lookup
            ON package_purchases(cliente_id, status, buyer_email, buyer_phone)
            """
        )
        package_purchase_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(package_purchases)").fetchall()
        }
        # Compra ONLINE de bonos (tienda publica): enlaza la compra con su pago Stripe
        # para que el webhook sea idempotente (mismo patron que gift_cards/product_sales).
        if "customer_payment_id" not in package_purchase_columns:
            connection.execute(
                "ALTER TABLE package_purchases ADD COLUMN customer_payment_id TEXT NOT NULL DEFAULT ''"
            )
        # Wallet publica del bono (jul 2026): token secreto para la pagina
        # /bono/{cliente_id}/{wallet_token} + snapshot inicial de sesiones para
        # mostrar progreso (usadas/total) y detectar consumo al reembolsar.
        if "wallet_token" not in package_purchase_columns:
            connection.execute(
                "ALTER TABLE package_purchases ADD COLUMN wallet_token TEXT NOT NULL DEFAULT ''"
            )
        # Avisos de ciclo de vida (jul 2026): sellado de "caducidad proxima" y de
        # "bono agotado -> recompra" para que el worker no repita emails.
        for lifecycle_column in ("expiry_notice_sent_at", "rebuy_notice_sent_at"):
            if lifecycle_column not in package_purchase_columns:
                connection.execute(
                    f"ALTER TABLE package_purchases ADD COLUMN {lifecycle_column} TEXT NOT NULL DEFAULT ''"
                )
        if "initial_json" not in package_purchase_columns:
            connection.execute(
                "ALTER TABLE package_purchases ADD COLUMN initial_json TEXT NOT NULL DEFAULT ''"
            )
            # Backfill best-effort: para compras previas el snapshot inicial se
            # aproxima con lo que quede (no hay historico mejor).
            connection.execute(
                "UPDATE package_purchases SET initial_json = remaining_json WHERE initial_json = ''"
            )
        for row in connection.execute(
            "SELECT id FROM package_purchases WHERE wallet_token = ''"
        ).fetchall():
            connection.execute(
                "UPDATE package_purchases SET wallet_token = ? WHERE id = ?",
                (f"pw_{secrets.token_urlsafe(18)}", row[0]),
            )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_package_purchases_wallet
            ON package_purchases(wallet_token)
            """
        )
        # Imagen de bono (URL configurable; tienda online + mostrador).
        package_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(packages)").fetchall()
        }
        if "image_url" not in package_columns:
            connection.execute("ALTER TABLE packages ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gift_cards (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                code TEXT NOT NULL,
                initial_cents INTEGER NOT NULL DEFAULT 0,
                balance_cents INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'eur',
                status TEXT NOT NULL DEFAULT 'active',
                buyer_name TEXT NOT NULL DEFAULT '',
                buyer_email TEXT NOT NULL DEFAULT '',
                recipient_name TEXT NOT NULL DEFAULT '',
                recipient_email TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL DEFAULT '',
                location_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_gift_cards_code
            ON gift_cards(cliente_id, code)
            """
        )
        # Compra publica de tarjetas regalo (jul 2026): mensaje del comprador, envio
        # programado y trazabilidad del pago. Migracion idempotente.
        gift_cards_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(gift_cards)").fetchall()
        }
        for column_name, definition in (
            ("message", "TEXT NOT NULL DEFAULT ''"),
            ("scheduled_send_at", "TEXT NOT NULL DEFAULT ''"),
            ("sent_at", "TEXT NOT NULL DEFAULT ''"),
            ("customer_payment_id", "TEXT NOT NULL DEFAULT ''"),
            # Aviso de caducidad proxima (worker de ciclo de vida, jul 2026).
            ("expiry_notice_sent_at", "TEXT NOT NULL DEFAULT ''"),
            # F2: personalizacion de la compra publica.
            ("accent_color", "TEXT NOT NULL DEFAULT ''"),
            ("hide_value", "INTEGER NOT NULL DEFAULT 0"),
            ("hide_expiry", "INTEGER NOT NULL DEFAULT 0"),
            ("service_name", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column_name not in gift_cards_columns:
                connection.execute(f"ALTER TABLE gift_cards ADD COLUMN {column_name} {definition}")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gift_card_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id TEXT NOT NULL,
                gift_card_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                amount_cents INTEGER NOT NULL DEFAULT 0,
                balance_after_cents INTEGER NOT NULL DEFAULT 0,
                booking_id TEXT NOT NULL DEFAULT '',
                sale_id TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_gift_card_tx_lookup
            ON gift_card_transactions(cliente_id, gift_card_id, created_at)
            """
        )
        agenda_columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(agenda_blocks)").fetchall()
        }
        if "employee_id" not in agenda_columns:
            connection.execute("ALTER TABLE agenda_blocks ADD COLUMN employee_id TEXT NOT NULL DEFAULT ''")
        if "location_id" not in agenda_columns:
            connection.execute("ALTER TABLE agenda_blocks ADD COLUMN location_id TEXT NOT NULL DEFAULT ''")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_manage_token
            ON bookings(manage_token)
            WHERE manage_token <> ''
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bookings_time_scope
            ON bookings(cliente_id, status, start_at)
            """
        )
        # Busquedas calientes de la gestion de citas: por numero de reserva (chat/voz/WA)
        # y por manage_token (enlace publico del email; antes era un SCAN completo).
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bookings_code
            ON bookings(cliente_id, booking_code)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bookings_manage_token
            ON bookings(manage_token)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                origin TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                last_message_at TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                intents_json TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_lookup
            ON chat_sessions(cliente_id, last_message_at)
            """
        )
        # Numero de WhatsApp POR EL QUE ENTRO la conversacion. Sin esto, responder a
        # mano desde el panel salia por el numero de la config del tenant, que no tiene
        # por que ser el mismo (numero de demo compartido, o un numero por centro).
        chat_session_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(chat_sessions)").fetchall()
        }
        if "wa_phone_number_id" not in chat_session_columns:
            connection.execute(
                "ALTER TABLE chat_sessions ADD COLUMN wa_phone_number_id TEXT NOT NULL DEFAULT ''"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                cliente_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                intent TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session
            ON chat_messages(session_id, id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analytics_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_name TEXT NOT NULL,
                event_source TEXT NOT NULL DEFAULT '',
                cliente_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                page_path TEXT NOT NULL DEFAULT '',
                page_url TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                user_agent TEXT NOT NULL DEFAULT '',
                ip_hash TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_analytics_events_lookup
            ON analytics_events(created_at, event_name, cliente_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_inbound_messages (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                phone_number_id TEXT NOT NULL,
                from_number TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_whatsapp_inbound_lookup
            ON whatsapp_inbound_messages(cliente_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                display_name TEXT NOT NULL,
                cliente_id TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user
            ON auth_sessions(user_id, expires_at)
            """
        )
        # Sem 6 migration: admin impersonation metadata on auth_sessions
        session_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(auth_sessions)").fetchall()
        }
        if "impersonator_user_id" not in session_columns:
            connection.execute(
                "ALTER TABLE auth_sessions ADD COLUMN impersonator_user_id TEXT NOT NULL DEFAULT ''"
            )
        if "impersonator_email" not in session_columns:
            connection.execute(
                "ALTER TABLE auth_sessions ADD COLUMN impersonator_email TEXT NOT NULL DEFAULT ''"
            )
        if "impersonator_ip" not in session_columns:
            connection.execute(
                "ALTER TABLE auth_sessions ADD COLUMN impersonator_ip TEXT NOT NULL DEFAULT ''"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_impersonations (
                id TEXT PRIMARY KEY,
                admin_user_id TEXT NOT NULL,
                admin_email TEXT NOT NULL,
                target_user_id TEXT NOT NULL,
                target_cliente_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL DEFAULT '',
                ip TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_admin_imp_admin ON admin_impersonations(admin_user_id, started_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_admin_imp_target ON admin_impersonations(target_cliente_id, started_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT NOT NULL DEFAULT '',
                requested_from_ip TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user
            ON password_reset_tokens(user_id, expires_at)
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                nonce TEXT NOT NULL,
                intent TEXT NOT NULL DEFAULT 'login',
                claim TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gmail_oauth_states (
                state TEXT PRIMARY KEY,
                admin_user_id TEXT NOT NULL DEFAULT '',
                cliente_id TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gmail_connections (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                access_token_encrypted TEXT NOT NULL DEFAULT '',
                refresh_token_encrypted TEXT NOT NULL DEFAULT '',
                expires_at REAL NOT NULL DEFAULT 0,
                scopes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_used_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        gmail_state_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(gmail_oauth_states)").fetchall()
        }
        if "cliente_id" not in gmail_state_columns:
            connection.execute("ALTER TABLE gmail_oauth_states ADD COLUMN cliente_id TEXT NOT NULL DEFAULT ''")
        gmail_connection_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(gmail_connections)").fetchall()
        }
        if "cliente_id" not in gmail_connection_columns:
            connection.execute("ALTER TABLE gmail_connections ADD COLUMN cliente_id TEXT NOT NULL DEFAULT ''")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_gmail_connections_cliente ON gmail_connections(cliente_id) WHERE cliente_id <> ''"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS booking_payments (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                booking_id TEXT NOT NULL UNIQUE,
                stripe_account_id TEXT NOT NULL DEFAULT '',
                checkout_session_id TEXT NOT NULL DEFAULT '',
                payment_intent_id TEXT NOT NULL DEFAULT '',
                amount_cents INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'eur',
                status TEXT NOT NULL DEFAULT 'pending',
                checkout_url TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                paid_at TEXT NOT NULL DEFAULT '',
                refunded_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_booking_payments_session ON booking_payments(checkout_session_id) WHERE checkout_session_id <> ''"
        )
        booking_payment_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(booking_payments)").fetchall()
        }
        if "capture_method" not in booking_payment_columns:
            connection.execute(
                "ALTER TABLE booking_payments ADD COLUMN capture_method TEXT NOT NULL DEFAULT 'automatic'"
            )

        # --- Vantelia 2.0 self-serve tables (Sem 1 migration) ---
        user_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if "google_sub" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN google_sub TEXT NOT NULL DEFAULT ''")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub) WHERE google_sub <> ''"
            )
        if "email_verified" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
        if "signup_source" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN signup_source TEXT NOT NULL DEFAULT 'manual'")
        if "avatar_url" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT NOT NULL DEFAULT ''")
        if "portal_role" not in user_columns:
            # Rol granular dentro del negocio: owner > manager > staff.
            connection.execute("ALTER TABLE users ADD COLUMN portal_role TEXT NOT NULL DEFAULT 'owner'")

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS clientes (
                cliente_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL DEFAULT '',
                plan TEXT NOT NULL DEFAULT 'free',
                nombre TEXT NOT NULL DEFAULT '',
                website_url TEXT NOT NULL DEFAULT '',
                config_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'legacy'
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_clientes_owner ON clientes(owner_user_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_clientes_plan ON clientes(plan)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS demo_tenants_registry (
                email TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL DEFAULT '',
                created_ts REAL NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'generating',
                lease_owner TEXT NOT NULL DEFAULT '',
                lease_expires_ts REAL NOT NULL DEFAULT 0,
                updated_ts REAL NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_demo_registry_cliente "
            "ON demo_tenants_registry(cliente_id) WHERE cliente_id <> ''"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS demo_registry_meta (
                   key TEXT PRIMARY KEY,
                   value TEXT NOT NULL DEFAULT ''
               )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS demo_tenant_cleanup_queue (
                   cliente_id TEXT PRIMARY KEY,
                   email TEXT NOT NULL DEFAULT '',
                   created_ts REAL NOT NULL DEFAULT 0,
                   reason TEXT NOT NULL DEFAULT '',
                   state TEXT NOT NULL DEFAULT 'queued',
                   lease_owner TEXT NOT NULL DEFAULT '',
                   lease_expires_ts REAL NOT NULL DEFAULT 0,
                   updated_ts REAL NOT NULL DEFAULT 0
               )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_demo_cleanup_state "
            "ON demo_tenant_cleanup_queue(state, lease_expires_ts)"
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                cliente_id TEXT NOT NULL DEFAULT '',
                plan TEXT NOT NULL DEFAULT 'free',
                status TEXT NOT NULL DEFAULT 'active',
                stripe_customer_id TEXT NOT NULL DEFAULT '',
                stripe_subscription_id TEXT NOT NULL DEFAULT '',
                stripe_price_id TEXT NOT NULL DEFAULT '',
                current_period_start TEXT NOT NULL DEFAULT '',
                current_period_end TEXT NOT NULL DEFAULT '',
                messages_quota INTEGER NOT NULL DEFAULT 50,
                messages_used_period INTEGER NOT NULL DEFAULT 0,
                cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_cust ON subscriptions(stripe_customer_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_sub ON subscriptions(stripe_subscription_id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS stripe_connected_accounts (
                cliente_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL DEFAULT '',
                stripe_account_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                requirements_due INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS kb_documents (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                mime_type TEXT NOT NULL DEFAULT '',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'upload',
                source_url TEXT NOT NULL DEFAULT '',
                storage_path TEXT NOT NULL DEFAULT '',
                indexed_at TEXT NOT NULL DEFAULT '',
                uploaded_at TEXT NOT NULL,
                uploaded_by_user_id TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_kb_documents_cliente ON kb_documents(cliente_id)"
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_leads (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                session_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'chat',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_bot_leads_cliente ON bot_leads(cliente_id, created_at)"
        )

        # Leads del formulario publico /consulta (web comercial). Se persisten
        # SIEMPRE antes de intentar el email: un fallo SMTP nunca pierde un lead.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS consulta_leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                telefono TEXT NOT NULL DEFAULT '',
                empresa TEXT NOT NULL DEFAULT '',
                servicio TEXT NOT NULL DEFAULT '',
                mensaje TEXT NOT NULL DEFAULT '',
                ip TEXT NOT NULL DEFAULT '',
                notif_sent INTEGER NOT NULL DEFAULT 0,
                confirm_sent INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                attended_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_consulta_leads_status ON consulta_leads(status, created_at)"
        )

        # CRM ligero: identidad consolidada y enlaces a registros operativos.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS crm_contacts (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                email_normalized TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                phone_normalized TEXT NOT NULL DEFAULT '',
                search_text TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'nuevo',
                notes TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                owner TEXT NOT NULL DEFAULT '',
                next_action TEXT NOT NULL DEFAULT '',
                next_action_at TEXT NOT NULL DEFAULT '',
                source_first TEXT NOT NULL DEFAULT '',
                source_last TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_crm_contacts_cliente ON crm_contacts(cliente_id, updated_at)"
        )
        crm_contact_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(crm_contacts)").fetchall()
        }
        if "search_text" not in crm_contact_columns:
            connection.execute("ALTER TABLE crm_contacts ADD COLUMN search_text TEXT NOT NULL DEFAULT ''")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_crm_contacts_email
            ON crm_contacts(cliente_id, email_normalized)
            WHERE email_normalized <> ''
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_crm_contacts_phone
            ON crm_contacts(cliente_id, phone_normalized)
            WHERE phone_normalized <> ''
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_crm_contacts_status ON crm_contacts(cliente_id, status, last_seen_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_crm_contacts_owner ON crm_contacts(cliente_id, owner, last_seen_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_crm_contacts_source ON crm_contacts(cliente_id, source_last, last_seen_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_crm_contacts_next_action ON crm_contacts(cliente_id, next_action_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_crm_contacts_created ON crm_contacts(cliente_id, created_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS crm_contact_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id TEXT NOT NULL,
                contact_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(cliente_id, entity_type, entity_id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_crm_contact_links_contact ON crm_contact_links(cliente_id, contact_id, created_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_crm_contact_links_source ON crm_contact_links(cliente_id, source, contact_id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS crm_contact_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id TEXT NOT NULL,
                contact_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT 'system',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_crm_contact_audit_contact ON crm_contact_audit(cliente_id, contact_id, id)"
        )

        # Stripe Connect para pagos de clientes finales. Separado de subscriptions.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_payment_accounts (
                cliente_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL DEFAULT 'stripe_connect',
                stripe_account_id TEXT NOT NULL DEFAULT '',
                charges_enabled INTEGER NOT NULL DEFAULT 0,
                payouts_enabled INTEGER NOT NULL DEFAULT 0,
                details_submitted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_accounts_stripe ON client_payment_accounts(stripe_account_id) WHERE stripe_account_id <> ''"
        )
        payment_account_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(client_payment_accounts)").fetchall()
        }
        if "ai_send_enabled" not in payment_account_columns:
            connection.execute(
                "ALTER TABLE client_payment_accounts ADD COLUMN ai_send_enabled INTEGER NOT NULL DEFAULT 0"
            )
        # Que metodos de pago quiere el negocio. La tarjeta no se puede quitar; estos
        # dos si. Nacen encendidos porque es lo que quiere un negocio espanol, y a
        # partir de ahi manda lo que diga el panel (ver stripe_gateway.sync_payment_methods).
        for columna in ("bizum_enabled", "wallets_enabled"):
            if columna not in payment_account_columns:
                connection.execute(
                    "ALTER TABLE client_payment_accounts ADD COLUMN %s INTEGER NOT NULL DEFAULT 1" % columna
                )
        # Ultimo estado conocido de la capability de Bizum en Stripe. Se guarda para
        # que al abrir la pantalla se sepa sin tener que llamar a Stripe.
        if "bizum_status" not in payment_account_columns:
            connection.execute(
                "ALTER TABLE client_payment_accounts ADD COLUMN bizum_status TEXT NOT NULL DEFAULT ''"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS service_payment_policies (
                cliente_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'none',
                deposit_value INTEGER NOT NULL DEFAULT 0,
                confirm_booking_on_paid INTEGER NOT NULL DEFAULT 1,
                refund_policy_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (cliente_id, service_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_payments (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                contact_id TEXT NOT NULL DEFAULT '',
                booking_id TEXT NOT NULL DEFAULT '',
                service_id TEXT NOT NULL DEFAULT '',
                service_name TEXT NOT NULL DEFAULT '',
                stripe_account_id TEXT NOT NULL DEFAULT '',
                stripe_checkout_session_id TEXT NOT NULL DEFAULT '',
                stripe_payment_intent_id TEXT NOT NULL DEFAULT '',
                amount_cents INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'eur',
                status TEXT NOT NULL DEFAULT 'pending',
                checkout_url TEXT NOT NULL DEFAULT '',
                paid_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_payments_client ON customer_payments(cliente_id, created_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_payments_booking ON customer_payments(cliente_id, booking_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_payments_contact ON customer_payments(cliente_id, contact_id)"
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_payments_session
            ON customer_payments(stripe_checkout_session_id)
            WHERE stripe_checkout_session_id <> ''
            """
        )
        # Cobro POS (mostrador / productos sobre la cita): kind + lineas del carrito.
        customer_payments_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(customer_payments)").fetchall()
        }
        for column_name, definition in {
            "kind": "TEXT NOT NULL DEFAULT 'booking'",
            "line_items_json": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column_name not in customer_payments_columns:
                connection.execute(f"ALTER TABLE customer_payments ADD COLUMN {column_name} {definition}")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_payment_events (
                stripe_event_id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                payment_id TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_payment_events_client ON customer_payment_events(cliente_id, created_at)"
        )

        # Ajustes globales editables desde admin (no secretos).
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )

        # Canales de envio multi-tenant. Los secretos OAuth se guardan cifrados.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_channel_settings (
                cliente_id TEXT PRIMARY KEY,
                email_provider TEXT NOT NULL DEFAULT 'vantelia_smtp',
                email_fallback_enabled INTEGER NOT NULL DEFAULT 1,
                sms_mode TEXT NOT NULL DEFAULT 'vantelia_default',
                sms_sender TEXT NOT NULL DEFAULT '',
                sms_sender_status TEXT NOT NULL DEFAULT 'not_configured',
                sms_twilio_account_sid_encrypted TEXT NOT NULL DEFAULT '',
                sms_twilio_auth_token_encrypted TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        channel_settings_cols = {
            row[1] for row in connection.execute("PRAGMA table_info(client_channel_settings)").fetchall()
        }
        if "ai_rebooking_enabled" not in channel_settings_cols:
            connection.execute(
                "ALTER TABLE client_channel_settings ADD COLUMN ai_rebooking_enabled INTEGER NOT NULL DEFAULT 0"
            )
        for column_name, definition in {
            "email_smtp_host": "TEXT NOT NULL DEFAULT ''",
            "email_smtp_port": "INTEGER NOT NULL DEFAULT 587",
            "email_smtp_username": "TEXT NOT NULL DEFAULT ''",
            "email_smtp_password_encrypted": "TEXT NOT NULL DEFAULT ''",
            "email_smtp_from_email": "TEXT NOT NULL DEFAULT ''",
            "email_smtp_from_name": "TEXT NOT NULL DEFAULT ''",
            "email_smtp_reply_to": "TEXT NOT NULL DEFAULT ''",
            "email_smtp_starttls": "INTEGER NOT NULL DEFAULT 1",
        }.items():
            if column_name not in channel_settings_cols:
                connection.execute(f"ALTER TABLE client_channel_settings ADD COLUMN {column_name} {definition}")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_rebooking_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id TEXT NOT NULL,
                contact_phone TEXT NOT NULL,
                servicio TEXT NOT NULL DEFAULT '',
                sent_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ai_rebooking_log_lookup
            ON ai_rebooking_log(cliente_id, contact_phone, sent_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_oauth_connections (
                cliente_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                account_email TEXT NOT NULL DEFAULT '',
                account_name TEXT NOT NULL DEFAULT '',
                scopes_json TEXT NOT NULL DEFAULT '[]',
                access_token_encrypted TEXT NOT NULL DEFAULT '',
                refresh_token_encrypted TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (cliente_id, provider)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_channel_oauth_states (
                state_hash TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                code_verifier_encrypted TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_channel_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                event_type TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT '',
                success INTEGER NOT NULL DEFAULT 0,
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_client_channel_audit_client ON client_channel_audit(cliente_id, created_at)"
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_channel_requests (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                request_type TEXT NOT NULL,
                requested_sender TEXT NOT NULL DEFAULT '',
                requested_phone TEXT NOT NULL DEFAULT '',
                contact_name TEXT NOT NULL DEFAULT '',
                contact_email TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                admin_notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_client_channel_requests_status ON client_channel_requests(status, created_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_client_channel_requests_client ON client_channel_requests(cliente_id, created_at)"
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_chat_sessions (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                chat_session_id TEXT NOT NULL,
                agent_user_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                started_at TEXT NOT NULL,
                claimed_at TEXT NOT NULL DEFAULT '',
                ended_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_live_chat_cliente ON live_chat_sessions(cliente_id, status)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_live_chat_session ON live_chat_sessions(chat_session_id)"
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS kb_qa (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by_user_id TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_kb_qa_cliente ON kb_qa(cliente_id, created_at)"
        )

        # Respuestas automaticas por palabra clave (opt-in por tenant, ver backend/keywords.py).
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS keyword_rules (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                keywords_json TEXT NOT NULL DEFAULT '[]',
                reply TEXT NOT NULL,
                match_mode TEXT NOT NULL DEFAULT 'any',
                active INTEGER NOT NULL DEFAULT 1,
                position INTEGER NOT NULL DEFAULT 0,
                hits INTEGER NOT NULL DEFAULT 0,
                last_hit_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by_user_id TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_keyword_rules_cliente "
            "ON keyword_rules(cliente_id, active, position)"
        )

        # Numero de WhatsApp compartido para demos comerciales (backend/wa_demo.py):
        # un codigo por prospecto ata su telefono al tenant que le toca.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_demo_codes (
                code TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                expires_at TEXT NOT NULL DEFAULT '',
                uses INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_wa_demo_codes_cliente ON wa_demo_codes(cliente_id, created_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_demo_routes (
                phone TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                code TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_wa_demo_routes_code ON wa_demo_routes(code)"
        )

        # Intervencion humana sobre una conversacion (backend/inbox.py): mientras
        # existe la fila y no ha caducado, el asistente NO responde en ese chat.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_takeovers (
                session_id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                agent_user_id TEXT NOT NULL DEFAULT '',
                agent_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_takeovers_cliente ON chat_takeovers(cliente_id, expires_at)"
        )

        # Conexion self-service de WhatsApp por Embedded Signup (backend/wa_onboarding.py).
        # Guarda el token PROPIO del negocio cifrado: con Coexistence su numero sigue en
        # la app del movil y a la vez responde por la API.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_whatsapp_accounts (
                cliente_id TEXT PRIMARY KEY,
                waba_id TEXT NOT NULL DEFAULT '',
                phone_number_id TEXT NOT NULL DEFAULT '',
                display_phone_number TEXT NOT NULL DEFAULT '',
                verified_name TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT 'api',
                access_token_encrypted TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'connected',
                last_error TEXT NOT NULL DEFAULT '',
                connected_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_client_whatsapp_phone "
            "ON client_whatsapp_accounts(phone_number_id, status)"
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS message_usage_events (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '',
                period_start TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'bot_reply',
                tokens_input INTEGER NOT NULL DEFAULT 0,
                tokens_output INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_usage_user_period ON message_usage_events(user_id, period_start)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_usage_cliente_period ON message_usage_events(cliente_id, period_start)"
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_sid TEXT UNIQUE NOT NULL,
                cliente_id TEXT NOT NULL,
                from_number TEXT NOT NULL DEFAULT '',
                to_number TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT '',
                ended_at TEXT NOT NULL DEFAULT '',
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'in_progress',
                transcript_json TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL DEFAULT '',
                booking_created INTEGER NOT NULL DEFAULT 0,
                sms_sent INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # Llamadas salientes (confirmacion de citas): direccion + cita + proposito.
        voice_calls_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(voice_calls)").fetchall()
        }
        for column_name, definition in {
            "direction": "TEXT NOT NULL DEFAULT 'inbound'",
            "purpose": "TEXT NOT NULL DEFAULT ''",
            "booking_id": "TEXT NOT NULL DEFAULT ''",
            # Etiqueta del resultado de la llamada para informes (reservada/confirmada/
            # cancelada/reprogramada/transferida/sin_accion).
            "outcome": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column_name not in voice_calls_columns:
                connection.execute(f"ALTER TABLE voice_calls ADD COLUMN {column_name} {definition}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_calls_cliente ON voice_calls(cliente_id, started_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_calls_status ON voice_calls(status)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS growth_daily (
                activity_date TEXT PRIMARY KEY,
                researched INTEGER NOT NULL DEFAULT 0,
                contacts INTEGER NOT NULL DEFAULT 0,
                followups INTEGER NOT NULL DEFAULT 0,
                calls INTEGER NOT NULL DEFAULT 0,
                positive_replies INTEGER NOT NULL DEFAULT 0,
                conversations INTEGER NOT NULL DEFAULT 0,
                meetings INTEGER NOT NULL DEFAULT 0,
                proposals INTEGER NOT NULL DEFAULT 0,
                won INTEGER NOT NULL DEFAULT 0,
                eur_sold REAL NOT NULL DEFAULT 0,
                new_recurring INTEGER NOT NULL DEFAULT 0,
                delivery_hours REAL NOT NULL DEFAULT 0,
                learning TEXT NOT NULL DEFAULT '',
                blocker TEXT NOT NULL DEFAULT '',
                next_action TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS growth_opportunities (
                id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                campaign TEXT NOT NULL DEFAULT '',
                offer TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT 'identificada',
                value_eur REAL NOT NULL DEFAULT 0,
                decision_maker TEXT NOT NULL DEFAULT '',
                contact TEXT NOT NULL DEFAULT '',
                problem TEXT NOT NULL DEFAULT '',
                next_action TEXT NOT NULL DEFAULT '',
                next_action_date TEXT NOT NULL DEFAULT '',
                decision_date TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                lost_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_growth_opportunities_stage ON growth_opportunities(stage, next_action_date)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS growth_opportunity_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_growth_opportunity_audit ON growth_opportunity_audit(opportunity_id, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS growth_weekly_reviews (
                week_start TEXT PRIMARY KEY,
                generated_json TEXT NOT NULL DEFAULT '{}',
                decision TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS growth_plan_tasks (
                task_key TEXT PRIMARY KEY,
                completed INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )

        connection.commit()


def _get_db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(settings.DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


# --- Vantelia 2.0: clientes table helpers (Sem 1) ---
# CONFIG_CLIENTES (in-memory dict from config.json) remains the source of truth
# at runtime. The clientes SQL table is a mirror used for queries that JSON can't
# answer cheaply (ownership lookups, plan aggregation, joins). _persist_configs_to_disk
# writes both representations atomically so they never drift.

def db_get_client_row(cliente_id: str) -> Optional[sqlite3.Row]:
    with _get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM clientes WHERE cliente_id = ?", (cliente_id,)
        ).fetchone()


def db_get_client_owner(cliente_id: str) -> str:
    row = db_get_client_row(cliente_id)
    return row["owner_user_id"] if row else ""


def db_set_client_owner(cliente_id: str, owner_user_id: str, *, source: str = "self_serve") -> None:
    now_iso = timeutils._utc_now().isoformat()
    with _get_db_connection() as connection:
        connection.execute(
            """
            UPDATE clientes
            SET owner_user_id = ?, source = ?, updated_at = ?
            WHERE cliente_id = ?
            """,
            (owner_user_id, source, now_iso, cliente_id),
        )
        connection.commit()


def db_get_subscription_for_user(user_id: str) -> Optional[sqlite3.Row]:
    if not user_id:
        return None
    with _get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)
        ).fetchone()


def _subscription_period_start_now() -> str:
    """Calendar month start in UTC ISO format."""
    now = timeutils._utc_now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _maybe_reset_subscription_period(sub: sqlite3.Row) -> sqlite3.Row:
    """For free plans we reset usage on calendar month boundaries. For paid plans
    we trust Stripe's current_period_start/end and only reset when we cross it.
    Returns the (possibly refreshed) subscription row."""
    if not sub:
        return sub
    now_iso = timeutils._utc_now().isoformat()
    plan = (sub["plan"] or "free").lower()
    current_start = sub["current_period_start"] or ""
    needs_reset = False
    new_period_start = current_start
    if plan == "free":
        month_start = _subscription_period_start_now()
        if not current_start or current_start < month_start:
            needs_reset = True
            new_period_start = month_start
    else:
        # Paid plans rely on Stripe webhook to bump current_period_start when a
        # new invoice posts. If current_period_end has passed and Stripe hasn't
        # updated us yet, leave usage alone to avoid double-billing edge cases.
        pass
    if not needs_reset:
        return sub
    with _get_db_connection() as connection:
        connection.execute(
            """
            UPDATE subscriptions
            SET messages_used_period = 0,
                current_period_start = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (new_period_start, now_iso, sub["id"]),
        )
        connection.commit()
        return connection.execute(
            "SELECT * FROM subscriptions WHERE id = ?", (sub["id"],)
        ).fetchone()


def db_subscription_for_cliente(cliente_id: str) -> Optional[sqlite3.Row]:
    """Return the self-serve subscription tied to the owner of this cliente_id, if any."""
    owner = db_get_client_owner(cliente_id)
    if not owner:
        return None
    return db_get_subscription_for_user(owner)


def db_increment_message_usage(cliente_id: str, *, count: int = 1, kind: str = "bot_reply") -> None:
    """Increment the owner's messages_used_period and log a usage event. No-op if
    the cliente has no self-serve owner (legacy clients keep their existing flow)."""
    owner = db_get_client_owner(cliente_id)
    if not owner:
        return
    sub = db_get_subscription_for_user(owner)
    if not sub:
        sub = db_ensure_free_subscription(owner, cliente_id=cliente_id)
    sub = _maybe_reset_subscription_period(sub)
    now_iso = timeutils._utc_now().isoformat()
    event_id = "evt_" + secrets.token_hex(10)
    period_start = sub["current_period_start"] or _subscription_period_start_now()
    with _get_db_connection() as connection:
        connection.execute(
            """
            UPDATE subscriptions
            SET messages_used_period = messages_used_period + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (max(1, int(count)), now_iso, sub["id"]),
        )
        connection.execute(
            """
            INSERT INTO message_usage_events
                (id, cliente_id, user_id, period_start, kind, tokens_input, tokens_output, created_at)
            VALUES (?, ?, ?, ?, ?, 0, 0, ?)
            """,
            (event_id, cliente_id, owner, period_start, kind, now_iso),
        )
        connection.commit()


def db_check_self_serve_quota(cliente_id: str) -> Optional[sqlite3.Row]:
    """Raise 402 if the owner's self-serve subscription has exceeded its quota.
    Returns the (possibly refreshed) subscription row if a check applied, else None.
    Legacy clients (no owner) get None and skip the check entirely."""
    owner = db_get_client_owner(cliente_id)
    if not owner:
        return None
    sub = db_get_subscription_for_user(owner)
    if not sub:
        return None
    sub = _maybe_reset_subscription_period(sub)
    status = (sub["status"] or "").lower()
    if status in {"canceled", "incomplete_expired", "unpaid"}:
        raise HTTPException(
            status_code=402,
            detail="Tu suscripcion no esta activa. Reactivala desde el panel.",
        )
    used = int(sub["messages_used_period"] or 0)
    quota = int(sub["messages_quota"] or 0)
    if quota > 0 and used >= quota:
        raise HTTPException(
            status_code=402,
            detail=f"Has alcanzado el limite mensual de tu plan ({quota} mensajes). Actualiza tu plan para seguir.",
        )
    return sub


def db_set_subscription_from_stripe(
    *,
    user_id: str,
    plan_slug: str,
    stripe_customer_id: str = "",
    stripe_subscription_id: str = "",
    stripe_price_id: str = "",
    status: str = "active",
    current_period_start: str = "",
    current_period_end: str = "",
    cancel_at_period_end: bool = False,
) -> sqlite3.Row:
    """Upsert a self-serve subscription tied to user_id after a Stripe event."""
    plan = settings._self_serve_plan(plan_slug)
    quota = int(plan["messages_quota"])
    now_iso = timeutils._utc_now().isoformat()
    existing = db_get_subscription_for_user(user_id)
    with _get_db_connection() as connection:
        if existing:
            # Only reset usage if the period actually advanced.
            reset_usage = bool(current_period_start) and (current_period_start != (existing["current_period_start"] or ""))
            if reset_usage:
                connection.execute(
                    """
                    UPDATE subscriptions SET
                        plan = ?, status = ?,
                        stripe_customer_id = ?, stripe_subscription_id = ?, stripe_price_id = ?,
                        current_period_start = ?, current_period_end = ?,
                        messages_quota = ?, messages_used_period = 0,
                        cancel_at_period_end = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        plan["slug"], status,
                        stripe_customer_id or existing["stripe_customer_id"],
                        stripe_subscription_id or existing["stripe_subscription_id"],
                        stripe_price_id or existing["stripe_price_id"],
                        current_period_start, current_period_end,
                        quota,
                        1 if cancel_at_period_end else 0, now_iso,
                        existing["id"],
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE subscriptions SET
                        plan = ?, status = ?,
                        stripe_customer_id = ?, stripe_subscription_id = ?, stripe_price_id = ?,
                        current_period_start = COALESCE(NULLIF(?, ''), current_period_start),
                        current_period_end = COALESCE(NULLIF(?, ''), current_period_end),
                        messages_quota = ?,
                        cancel_at_period_end = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        plan["slug"], status,
                        stripe_customer_id or existing["stripe_customer_id"],
                        stripe_subscription_id or existing["stripe_subscription_id"],
                        stripe_price_id or existing["stripe_price_id"],
                        current_period_start, current_period_end,
                        quota,
                        1 if cancel_at_period_end else 0, now_iso,
                        existing["id"],
                    ),
                )
            connection.commit()
            return connection.execute(
                "SELECT * FROM subscriptions WHERE id = ?", (existing["id"],)
            ).fetchone()
        else:
            sub_id = "sub_" + secrets.token_hex(10)
            connection.execute(
                """
                INSERT INTO subscriptions
                    (id, user_id, cliente_id, plan, status,
                     stripe_customer_id, stripe_subscription_id, stripe_price_id,
                     current_period_start, current_period_end,
                     messages_quota, messages_used_period, cancel_at_period_end,
                     created_at, updated_at)
                VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    sub_id, user_id, plan["slug"], status,
                    stripe_customer_id, stripe_subscription_id, stripe_price_id,
                    current_period_start, current_period_end,
                    quota,
                    1 if cancel_at_period_end else 0, now_iso, now_iso,
                ),
            )
            connection.commit()
            return connection.execute(
                "SELECT * FROM subscriptions WHERE id = ?", (sub_id,)
            ).fetchone()


def db_ensure_free_subscription(user_id: str, cliente_id: str = "") -> sqlite3.Row:
    """Ensure user has at least a free-tier subscription row. Returns it."""
    existing = db_get_subscription_for_user(user_id)
    if existing:
        return existing
    now_iso = timeutils._utc_now().isoformat()
    sub_id = secrets.token_hex(12)
    free_quota = int(settings.SELF_SERVE_PLANS.get("free", {}).get("messages_quota", int(os.getenv("DEFAULT_FREE_QUOTA", "50"))))
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO subscriptions
                (id, user_id, cliente_id, plan, status,
                 messages_quota, messages_used_period,
                 current_period_start, created_at, updated_at)
            VALUES (?, ?, ?, 'free', 'active', ?, 0, ?, ?, ?)
            """,
            (sub_id, user_id, cliente_id, free_quota, now_iso, now_iso, now_iso),
        )
        connection.commit()
        return connection.execute(
            "SELECT * FROM subscriptions WHERE id = ?", (sub_id,)
        ).fetchone()
