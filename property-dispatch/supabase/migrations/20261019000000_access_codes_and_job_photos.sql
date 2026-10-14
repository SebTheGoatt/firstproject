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
