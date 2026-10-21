-- Crew problem reports and marketing attribution. Safe to re-run.

-- "Report a problem" from the crew route screen: damage, equipment, access, delay. Private to the owner.
create table if not exists job_issues (
    id           uuid primary key default gen_random_uuid(),
    job_id       uuid not null references jobs(id) on delete cascade,
    member_id    uuid references crew_members(id) on delete set null,
    kind         text not null check (kind in ('damage', 'equipment', 'access', 'delay', 'other')),
    note         text not null default '' check (length(note) <= 1000),
    photo        text,                          -- data: URL (resized JPEG), served to the owner only
    has_photo    boolean generated always as (photo is not null) stored,   -- lists skip the image itself
    created_at   timestamptz not null default now(),
    resolved_at  timestamptz
);
create index if not exists job_issues_open_idx on job_issues (created_at) where resolved_at is null;
alter table job_issues enable row level security;
grant select, insert, update, delete on job_issues to service_role;

-- Where a booking came from (?ref= on a QR code, flyer, social post), e.g. "yard-sign-klein". No personal data.
alter table jobs add column if not exists source text check (source is null or source ~ '^[a-z0-9-]{1,48}$');
create index if not exists jobs_source_idx on jobs (source, created_at) where source is not null;
