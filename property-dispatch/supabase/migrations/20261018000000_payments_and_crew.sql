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
