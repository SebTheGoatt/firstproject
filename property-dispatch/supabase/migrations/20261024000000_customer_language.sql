-- The language a customer booked in, so their texts (booking confirmation, "on the way",
-- pay link) come in English or Spanish. Existing bookings stay English.
alter table jobs
    add column lang text not null default 'en' check (lang in ('en', 'es'));
