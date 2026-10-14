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
