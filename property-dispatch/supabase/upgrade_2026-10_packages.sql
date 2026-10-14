-- =====================================================================
--  M&A Lawn Care — database upgrade (Oct 2026)
--  Access codes + before/after photos, pricing + Texas sales tax,
--  donation split, mowing packages with charity giving, and add-ons.
--
--  HOW TO RUN: Supabase → SQL Editor → New query → paste ALL of this → Run.
--  Safe to run more than once: anything already added is skipped.
--  All-or-nothing: if any step fails, nothing is changed.
--  (Same as migrations 20261019 through 20261023.)
-- =====================================================================
begin;

-- ---------- 1. Customer access codes + private before/after photos ----------
alter table jobs add column if not exists access_code text unique
    check (access_code ~ '^[A-HJKMNP-Z2-9]{8}$');

update jobs
   set access_code = (
       select string_agg(substr('ABCDEFGHJKMNPQRSTUVWXYZ23456789', (floor(random() * 31) + 1)::int, 1), '')
       from generate_series(1, 8 + (id is null)::int * 0)
   )
 where access_code is null;

create table if not exists job_photos (
    id          uuid primary key default gen_random_uuid(),
    job_id      uuid not null references jobs(id) on delete cascade,
    member_id   uuid references crew_members(id) on delete set null,
    kind        text not null check (kind in ('before', 'after')),
    photo       text not null,
    created_at  timestamptz not null default now()
);
create index if not exists job_photos_job_idx on job_photos (job_id, created_at);
alter table job_photos enable row level security;
grant select, insert, update, delete on job_photos to service_role;

-- ---------- 2. Square-footage pricing + Texas sales tax ----------
alter table jobs
    add column if not exists lawn_sqft  integer check (lawn_sqft between 100 and 200000),
    add column if not exists subtotal   numeric(8, 2) check (subtotal >= 0),
    add column if not exists tax_rate   numeric(6, 5) check (tax_rate >= 0 and tax_rate < 0.2),
    add column if not exists tax_amount numeric(8, 2) check (tax_amount >= 0);

-- Existing bookings keep the price they were quoted (no tax added after the fact).
update jobs set subtotal = amount_due, tax_rate = 0, tax_amount = 0
 where subtotal is null and amount_due is not null;

-- ---------- 3. Per-sq-ft rate + where each donation goes ----------
alter table jobs
    add column if not exists sqft_rate      numeric(5, 4) check (sqft_rate > 0 and sqft_rate < 0.1),
    add column if not exists donation_split jsonb check (donation_split is null or jsonb_typeof(donation_split) = 'object');

-- ---------- 4. Mowing packages + charity giving from the price ----------
alter table jobs
    add column if not exists package        text check (package in ('standard', 'supporter', 'hero')),
    add column if not exists charity_rate   numeric(5, 4) check (charity_rate >= 0 and charity_rate < 1),
    add column if not exists charity_amount numeric(8, 2) check (charity_amount >= 0),
    add column if not exists giving_split   jsonb check (giving_split is null or jsonb_typeof(giving_split) = 'object');

-- ---------- 5. Add-ons to a mow: bins, gutters, holiday lights ----------
alter table jobs
    add column if not exists add_ons      jsonb not null default '[]' check (jsonb_typeof(add_ons) = 'array'),
    add column if not exists add_on_total numeric(8, 2) not null default 0 check (add_on_total >= 0);

commit;

-- Tell the API about the new columns right away.
notify pgrst, 'reload schema';

-- Quick check: should show 14 rows (13 new columns + the job_photos table).
select column_name from information_schema.columns
 where table_name = 'jobs' and column_name in ('access_code', 'lawn_sqft', 'subtotal', 'tax_rate', 'tax_amount',
       'sqft_rate', 'donation_split', 'package', 'charity_rate', 'charity_amount', 'giving_split',
       'add_ons', 'add_on_total')
union all
select 'job_photos table' from information_schema.tables where table_name = 'job_photos';
