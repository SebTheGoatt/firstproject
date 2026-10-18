-- Google review follow-up: when we asked this customer for a review (once per job, ~20 min after the crew leaves).
alter table jobs add column if not exists review_requested_at timestamptz;
create index if not exists jobs_review_due_idx on jobs (completed_at) where review_requested_at is null and status = 'completed';
