-- The backend talks to the database with the secret (service_role) key.
-- Grant it explicit access so the app works even on projects where new
-- tables aren't granted to API roles by default. anon/authenticated get nothing.
grant usage on schema public to service_role;
grant select, insert, update, delete on customers, jobs, routes, route_stops, leads to service_role;
grant select on daily_job_counts to service_role;
grant execute on function save_route(date, double precision, double precision, double precision,
                                     double precision, integer, integer, text, jsonb) to service_role;
