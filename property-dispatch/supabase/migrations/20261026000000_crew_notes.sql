-- Crew dashboard: a short private note per stop (gate code changed, dog in yard, etc.).
-- Only the crew and owner see it; it is never shown on the customer's visit page.
alter table route_stops add column if not exists crew_note text
    check (crew_note is null or length(crew_note) <= 500);
