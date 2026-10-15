-- One-paste setup: all migrations in order. Paste into Supabase SQL Editor and click Run once.

-- ===== migrations/20261014000000_init.sql =====
-- =====================================================================
--  Property Dispatch — initial schema
--  Run in Supabase: SQL Editor → paste → Run   (or `supabase db push`)
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------- Enums ----------------------------------------------------
create type service_type as enum ('mowing', 'bin_cleaning', 'gutters');

-- pending   : booked, still editable
-- scheduled : frozen by the 8 PM nightly run, has a route stop
-- completed : crew marked it done
-- cancelled : customer/admin cancelled
create type job_status as enum ('pending', 'scheduled', 'completed', 'cancelled');

-- ---------- Customers ------------------------------------------------
create table customers (
    id          uuid primary key default gen_random_uuid(),
    name        text not null check (length(trim(name)) > 0),
    phone       text not null check (phone ~ '^\+[1-9][0-9]{7,14}$'),  -- E.164
    created_at  timestamptz not null default now(),
    unique (phone)
);

-- ---------- Jobs -----------------------------------------------------
create table jobs (
    id                uuid primary key default gen_random_uuid(),
    customer_id       uuid not null references customers(id) on delete cascade,
    address           text not null,               -- as typed by the customer
    formatted_address text,                        -- as returned by the geocoder
    lat               double precision not null check (lat between -90 and 90),
    lng               double precision not null check (lng between -180 and 180),
    service           service_type not null,
    scheduled_date    date not null,
    status            job_status not null default 'pending',
    service_minutes   integer not null default 30 check (service_minutes > 0),
    frozen_at         timestamptz,
    completed_at      timestamptz,
    created_at        timestamptz not null default now()
);

create index jobs_date_status_idx on jobs (scheduled_date, status);

-- ---------- Routes (one per service day) -----------------------------
create table routes (
    id                  uuid primary key default gen_random_uuid(),
    route_date          date not null unique,
    start_lat           double precision not null,
    start_lng           double precision not null,
    end_lat             double precision not null,
    end_lng             double precision not null,
    total_distance_m    integer not null default 0,
    total_duration_s    integer not null default 0,
    matrix_source       text not null,             -- 'osrm' | 'haversine'
    optimized_at        timestamptz not null default now()
);

create table route_stops (
    id                  uuid primary key default gen_random_uuid(),
    route_id            uuid not null references routes(id) on delete cascade,
    job_id              uuid not null unique references jobs(id) on delete cascade,
    sequence            integer not null check (sequence >= 1),
    leg_distance_m      integer not null default 0,  -- from previous stop/base
    leg_duration_s      integer not null default 0,
    eta                 timestamptz,
    completed_at        timestamptz,
    notified_at         timestamptz,                 -- "you're next" SMS sent
    unique (route_id, sequence)
);

create index route_stops_route_seq_idx on route_stops (route_id, sequence);

-- ---------- Helpers --------------------------------------------------
-- Jobs-per-day count, used to enforce the daily quota at intake.
-- security_invoker keeps the view subject to the tables' RLS.
create view daily_job_counts with (security_invoker = true) as
select scheduled_date, count(*)::int as job_count
from jobs
where status <> 'cancelled'
group by scheduled_date;

-- Atomically replace a day's route and freeze its jobs.
-- p_stops: [{ "job_id": uuid, "sequence": int, "leg_distance_m": int,
--             "leg_duration_s": int, "eta": timestamptz }, ...]
create or replace function save_route(
    p_route_date        date,
    p_start_lat         double precision,
    p_start_lng         double precision,
    p_end_lat           double precision,
    p_end_lng           double precision,
    p_total_distance_m  integer,
    p_total_duration_s  integer,
    p_matrix_source     text,
    p_stops             jsonb
) returns uuid
language plpgsql
as $$
declare
    v_route_id uuid;
begin
    delete from routes where route_date = p_route_date;   -- cascades to stops

    insert into routes (route_date, start_lat, start_lng, end_lat, end_lng,
                        total_distance_m, total_duration_s, matrix_source)
    values (p_route_date, p_start_lat, p_start_lng, p_end_lat, p_end_lng,
            p_total_distance_m, p_total_duration_s, p_matrix_source)
    returning id into v_route_id;

    insert into route_stops (route_id, job_id, sequence, leg_distance_m,
                             leg_duration_s, eta)
    select v_route_id,
           (s->>'job_id')::uuid,
           (s->>'sequence')::int,
           (s->>'leg_distance_m')::int,
           (s->>'leg_duration_s')::int,
           (s->>'eta')::timestamptz
    from jsonb_array_elements(p_stops) as s;

    update jobs
       set status = 'scheduled', frozen_at = now()
     where id in (select (s->>'job_id')::uuid from jsonb_array_elements(p_stops) s)
       and status = 'pending';

    return v_route_id;
end;
$$;

-- ---------- Security -------------------------------------------------
-- All access goes through the FastAPI backend using the service-role key,
-- which bypasses RLS. Enabling RLS with no policies blocks the public
-- anon key from reading customer names/phones/addresses directly.
alter table customers   enable row level security;
alter table jobs        enable row level security;
alter table routes      enable row level security;
alter table route_stops enable row level security;

revoke all on function save_route from public, anon, authenticated;

-- ===== migrations/20261015000000_service_zones.sql =====
-- Record which geo-fenced service zone a job falls in and the price quoted
-- at booking time (mowing only; other services are quoted on site).
alter table jobs
    add column zone_key     text,
    add column quoted_price numeric(8, 2) check (quoted_price >= 0);

create index jobs_zone_idx on jobs (zone_key);

-- ===== migrations/20261016000000_leads.sql =====
-- Leads captured by POST /api/check-booking (booking-api) once an address
-- is confirmed inside a service zone, before the customer picks a date.
create table leads (
    id                uuid primary key default gen_random_uuid(),
    address           text not null,               -- as typed by the customer
    formatted_address text,                        -- as returned by the geocoder
    lat               double precision not null check (lat between -90 and 90),
    lng               double precision not null check (lng between -180 and 180),
    zone_name         text not null,
    base_mow_rate     numeric(8, 2) not null check (base_mow_rate >= 0),
    created_at        timestamptz not null default now()
);

create index leads_created_idx on leads (created_at desc);
create index leads_zone_idx on leads (zone_name);

-- Server-side inserts use the service-role key (bypasses RLS). No policies →
-- the public anon key can't read or write lead addresses.
alter table leads enable row level security;

-- ===== migrations/20261017000000_service_role_grants.sql =====
-- The backend talks to the database with the secret (service_role) key.
-- Grant it explicit access so the app works even on projects where new
-- tables aren't granted to API roles by default. anon/authenticated get nothing.
grant usage on schema public to service_role;
grant select, insert, update, delete on customers, jobs, routes, route_stops, leads to service_role;
grant select on daily_job_counts to service_role;
grant execute on function save_route(date, double precision, double precision, double precision,
                                     double precision, integer, integer, text, jsonb) to service_role;

-- ===== migrations/20261018000000_payments_and_crew.sql =====
-- "Pay your way" payments + crew member profiles and portfolios.

-- ---------- Payments on jobs -------------------------------------------
create type payment_method as enum ('cash', 'card');
create type payment_status as enum ('unpaid', 'paid');

alter table jobs
    add column payment_method    payment_method not null default 'cash',
    add column payment_status    payment_status not null default 'unpaid',
    add column amount_due        numeric(8, 2) check (amount_due >= 0),   -- final price (mowing: quoted at booking)
    add column donation          numeric(8, 2) not null default 0 check (donation >= 0),
    add column amount_paid       numeric(8, 2) check (amount_paid >= 0),  -- price + donation actually received
    add column paid_at           timestamptz,
    add column pay_token         text unique,                             -- secret for the customer's /pay link
    add column stripe_session_id text;

update jobs set amount_due = quoted_price where amount_due is null and quoted_price is not null;

-- ---------- Crew members ----------------------------------------------
create table crew_members (
    id                uuid primary key default gen_random_uuid(),
    slug              text not null unique check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    display_name      text not null check (length(trim(display_name)) > 0),
    role_title        text,
    bio               text check (length(bio) <= 1200),
    years_experience  integer check (years_experience between 0 and 80),
    specialties       text[] not null default '{}',
    service_branch    text,                       -- e.g. "U.S. Marine Corps veteran"
    accent_color      text not null default '#2f7d4f' check (accent_color ~ '^#[0-9a-fA-F]{6}$'),
    photo             text,                       -- data: URL (resized JPEG), served via /media/crew/{id}
    photo_updated_at  timestamptz,
    passcode_hash     text not null,              -- PBKDF2; never sent to browsers
    active            boolean not null default true,
    created_at        timestamptz not null default now()
);

create table portfolio_items (
    id          uuid primary key default gen_random_uuid(),
    member_id   uuid not null references crew_members(id) on delete cascade,
    job_id      uuid references jobs(id) on delete set null,
    service     service_type,
    caption     text check (length(caption) <= 280),
    photo       text not null,                    -- data: URL (resized JPEG), served via /media/portfolio/{id}
    created_at  timestamptz not null default now()
);

create index portfolio_member_idx on portfolio_items (member_id, created_at desc);

alter table route_stops
    add column completed_by uuid references crew_members(id) on delete set null;

create index route_stops_completed_by_idx on route_stops (completed_by, completed_at);

-- ---------- Security ---------------------------------------------------
alter table crew_members    enable row level security;
alter table portfolio_items enable row level security;

grant select, insert, update, delete on crew_members, portfolio_items to service_role;

-- ===== migrations/20261019000000_access_codes_and_job_photos.sql =====
-- Customer access codes (view your visit) and private before/after photos per job.

-- Codes look like K7MX3QPA (shown to customers as K7MX-3QPA): 8 characters,
-- no look-alikes (0/O, 1/I/L). Existing bookings get one too.
alter table jobs add column access_code text unique
    check (access_code ~ '^[A-HJKMNP-Z2-9]{8}$');

update jobs
   set access_code = (
       select string_agg(substr('ABCDEFGHJKMNPQRSTUVWXYZ23456789', (floor(random() * 31) + 1)::int, 1), '')
       from generate_series(1, 8 + (id is null)::int * 0)
   )
 where access_code is null;

-- Before/after photos of a customer's property. Private: shown only on that
-- customer's visit page (their access code), never on the public website.
create table job_photos (
    id          uuid primary key default gen_random_uuid(),
    job_id      uuid not null references jobs(id) on delete cascade,
    member_id   uuid references crew_members(id) on delete set null,
    kind        text not null check (kind in ('before', 'after')),
    photo       text not null,                 -- data: URL (resized JPEG), served via /media/visit/{id}
    created_at  timestamptz not null default now()
);

create index job_photos_job_idx on job_photos (job_id, created_at);

alter table job_photos enable row level security;
grant select, insert, update, delete on job_photos to service_role;

-- ===== migrations/20261020000000_pricing_and_sales_tax.sql =====
-- Square-footage pricing and Texas sales tax on each booking.
-- amount_due stays the total the customer owes (price + tax), so payments
-- work as before; these columns record how it was calculated.
alter table jobs
    add column lawn_sqft  integer check (lawn_sqft between 100 and 200000),  -- mowing: lawn size priced on
    add column subtotal   numeric(8, 2) check (subtotal >= 0),                -- price before tax
    add column tax_rate   numeric(6, 5) check (tax_rate >= 0 and tax_rate < 0.2),
    add column tax_amount numeric(8, 2) check (tax_amount >= 0);

-- Existing bookings keep the price they were quoted (no tax added after the fact).
update jobs set subtotal = amount_due, tax_rate = 0, tax_amount = 0
 where subtotal is null and amount_due is not null;

-- ===== migrations/20261021000000_rate_choice_and_donation_split.sql =====
-- Pay-what-you-can mowing rate and where each donation goes.
alter table jobs
    -- The per-square-foot rate the customer chose at booking (0.009, 0.010 or 0.011).
    -- The crew's on-site lawn-size correction re-prices at this same rate.
    add column sqft_rate      numeric(5, 4) check (sqft_rate > 0 and sqft_rate < 0.1),
    -- Each paid donation's split, saved to the cent when it's paid, e.g.
    -- {"vfw": 1.65, "nicu": 1.65, "at_risk_youth": 1.70}. The owner passes these on.
    -- Donations recorded before this migration have no split (they went to the business).
    add column donation_split jsonb check (donation_split is null or jsonb_typeof(donation_split) = 'object');

-- ===== migrations/20261022000000_packages_and_charity_giving.sql =====
-- Mowing packages: price = $50 base + rate × sq ft, and part of each price goes to charity
--   standard  0.9¢/sq ft,  2%   ·   supporter  1.0¢/sq ft,  7%   ·   hero  1.1¢/sq ft, 12%
alter table jobs
    add column package        text check (package in ('standard', 'supporter', 'hero')),
    add column charity_rate   numeric(5, 4) check (charity_rate >= 0 and charity_rate < 1),
    -- The business's gift from this job's price (not extra to the customer). Kept in step
    -- with the price while the job is unpaid; owed to charity once it's paid.
    add column charity_amount numeric(8, 2) check (charity_amount >= 0),
    -- charity_amount split between the causes to the cent, e.g. {"vfw": 1.96, "nicu": 1.96, "at_risk_youth": 2.03}
    add column giving_split   jsonb check (giving_split is null or jsonb_typeof(giving_split) = 'object');

-- ===== migrations/20261023000000_add_ons.sql =====
-- Add-ons to a mowing visit: bin cleaning ($15), gutter cleaning ($20),
-- holiday lighting hang-up ($30, Oct 15 – Jan 15). Their prices are in the job's subtotal.
alter table jobs
    -- e.g. [{"key": "gutters", "label": "Gutter cleaning", "price": 20.0}]
    add column add_ons      jsonb not null default '[]' check (jsonb_typeof(add_ons) = 'array'),
    add column add_on_total numeric(8, 2) not null default 0 check (add_on_total >= 0);

-- ===== migrations/20261024000000_customer_language.sql =====
-- The language a customer booked in, so their texts (booking confirmation, "on the way",
-- pay link) come in English or Spanish. Existing bookings stay English.
alter table jobs
    add column lang text not null default 'en' check (lang in ('en', 'es'));

