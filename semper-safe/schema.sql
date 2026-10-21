-- Enable UUID generation extension
create extension if not exists "uuid-ossp";

-- 1. CORPORATE ACCOUNTS TABLE
create table public.companies (
    id uuid default uuid_generate_v4() primary key,
    stripe_customer_id text unique not null,
    company_name text not null,
    account_status text default 'inactive' check (account_status in ('active', 'inactive', 'suspended')),
    tier text default 'starter' check (tier in ('starter', 'enterprise')),
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    updated_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- 2. COMPLIANCE AUDITS DATA STORAGE (With History Tracking Support)
create table public.safety_audits (
    id uuid default uuid_generate_v4() primary key,
    company_id uuid references public.companies(id) on delete cascade not null,
    filename text not null,
    compliance_score integer not null check (compliance_score >= 0 and compliance_score <= 100),
    raw_text_payload text,
    structured_findings jsonb not null,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- Enable Row Level Security (RLS) for absolute multi-tenant data safety.
-- No policies are defined, so only the service_role key (used by main.py) can read or write.
alter table public.companies enable row level security;
alter table public.safety_audits enable row level security;

-- Serves the history panel: one company's audits, newest first.
-- (stripe_customer_id is already indexed by its unique constraint)
create index idx_audits_company_created on public.safety_audits(company_id, created_at desc);
