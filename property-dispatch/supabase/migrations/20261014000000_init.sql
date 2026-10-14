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
