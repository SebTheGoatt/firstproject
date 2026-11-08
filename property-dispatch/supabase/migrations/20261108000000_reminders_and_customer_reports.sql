-- Day-before reminder texts and the customer's "Something not right?" button. Safe to re-run.

-- When we texted this customer the evening before their visit (once per booking, even if the route is rebuilt).
alter table jobs add column if not exists reminded_at timestamptz;

-- Customers can now report a problem privately from their visit page; it lands with the crew's reports.
alter table job_issues drop constraint if exists job_issues_kind_check;
alter table job_issues add constraint job_issues_kind_check
    check (kind in ('damage', 'equipment', 'access', 'delay', 'other', 'customer'));
