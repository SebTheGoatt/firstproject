-- Community: nominations for sponsored mows, and a payment method for them. Safe to re-run.

-- A sponsored mow is paid by a sponsor (the "Sponsor a neighbor's mow" add-on on their own booking), not by the
-- neighbor we mow for. Nothing is free: a sponsored mow is only scheduled against a paid sponsorship.
alter type payment_method add value if not exists 'sponsored';

-- Neighbors nominated for a sponsored mow (the public /community form). Private to the owner: never shown publicly.
create table if not exists nominations (
    id               uuid primary key default gen_random_uuid(),
    zone_key         text not null,
    nominee_name     text not null check (length(nominee_name) between 1 and 120),
    nominee_address  text not null check (length(nominee_address) between 5 and 200),
    nominee_phone    text check (nominee_phone is null or length(nominee_phone) <= 30),
    reason           text not null check (length(reason) between 1 and 600),
    nominator_name   text not null check (length(nominator_name) between 1 and 120),
    nominator_contact text not null check (length(nominator_contact) between 3 and 120),
    status           text not null default 'new' check (status in ('new', 'scheduled', 'declined')),
    job_id           uuid references jobs(id) on delete set null,
    created_at       timestamptz not null default now()
);
create index if not exists nominations_status_idx on nominations (status, created_at);
alter table nominations enable row level security;
grant select, insert, update, delete on nominations to service_role;
