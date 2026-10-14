-- Mowing packages: price = $50 base + rate × sq ft, and part of each price goes to charity
--   standard  0.9¢/sq ft,  2%   ·   supporter  1.0¢/sq ft,  7%   ·   hero  1.1¢/sq ft, 12%
alter table jobs
    add column package        text check (package in ('standard', 'supporter', 'hero')),
    add column charity_rate   numeric(5, 4) check (charity_rate >= 0 and charity_rate < 1),
    -- The business's gift from this job's price (not extra to the customer). Kept in step
    -- with the price while the job is unpaid; owed to charity once it's paid.
    add column charity_amount numeric(8, 2) check (charity_amount >= 0),
    -- charity_amount split between the causes to the cent, e.g. {"vfw": 1.96, "nicu": 1.96, "at_risk_youth": 2.03}
    add column giving_split   jsonb check (giving_split is null or jsonb_typeof(giving_split) = 'object');
