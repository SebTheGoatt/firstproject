-- Add-ons to a mowing visit: bin cleaning ($15), gutter cleaning ($20),
-- holiday lighting hang-up ($30, Oct 15 – Jan 15). Their prices are in the job's subtotal.
alter table jobs
    -- e.g. [{"key": "gutters", "label": "Gutter cleaning", "price": 20.0}]
    add column add_ons      jsonb not null default '[]' check (jsonb_typeof(add_ons) = 'array'),
    add column add_on_total numeric(8, 2) not null default 0 check (add_on_total >= 0);
