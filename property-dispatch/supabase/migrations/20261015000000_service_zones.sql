-- Record which geo-fenced service zone a job falls in and the price quoted
-- at booking time (mowing only; other services are quoted on site).
alter table jobs
    add column zone_key     text,
    add column quoted_price numeric(8, 2) check (quoted_price >= 0);

create index jobs_zone_idx on jobs (zone_key);
