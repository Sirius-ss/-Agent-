CREATE TABLE IF NOT EXISTS appliance_models (
 model_code text PRIMARY KEY, product_id varchar(40) UNIQUE NOT NULL REFERENCES products(id),
 display_name text NOT NULL, warranty_months integer NOT NULL CHECK(warranty_months>0), demo boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS appliances (
 device_id text PRIMARY KEY, order_item_id integer NOT NULL REFERENCES order_items(id),
 unit_no integer NOT NULL CHECK(unit_no>0), serial_no text UNIQUE NOT NULL, signed_on date,
 UNIQUE(order_item_id,unit_no)
);
CREATE TABLE IF NOT EXISTS repair_previews (
 preview_id text PRIMARY KEY, user_id varchar(40) NOT NULL REFERENCES users(id),
 device_id text NOT NULL REFERENCES appliances, description text NOT NULL, warranty_snapshot jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL, invalidated_at timestamptz
);
CREATE TABLE IF NOT EXISTS repair_tickets (
 ticket_id text PRIMARY KEY, preview_id text UNIQUE NOT NULL REFERENCES repair_previews,
 device_id text NOT NULL REFERENCES appliances, description text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), status text NOT NULL CHECK(status='PENDING')
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_device ON repair_tickets(device_id) WHERE status='PENDING';
