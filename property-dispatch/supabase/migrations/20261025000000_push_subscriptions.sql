-- Phones that tapped "Get updates on this phone" on their visit page, so we can send
-- "crew is on the way" and "all done" notifications. One row per phone/browser.
create table if not exists push_subscriptions (
    id          uuid primary key default gen_random_uuid(),
    job_id      uuid not null references jobs(id) on delete cascade,
    endpoint    text not null unique,
    p256dh      text not null,
    auth        text not null,
    lang        text not null default 'en' check (lang in ('en', 'es')),
    visit_path  text not null,
    created_at  timestamptz not null default now()
);

create index if not exists push_subscriptions_job_idx on push_subscriptions (job_id);

alter table push_subscriptions enable row level security;
grant select, insert, update, delete on push_subscriptions to service_role;

notify pgrst, 'reload schema';
