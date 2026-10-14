-- Pay-what-you-can mowing rate and where each donation goes.
alter table jobs
    -- The per-square-foot rate the customer chose at booking (0.009, 0.010 or 0.011).
    -- The crew's on-site lawn-size correction re-prices at this same rate.
    add column sqft_rate      numeric(5, 4) check (sqft_rate > 0 and sqft_rate < 0.1),
    -- Each paid donation's split, saved to the cent when it's paid, e.g.
    -- {"vfw": 1.65, "nicu": 1.65, "at_risk_youth": 1.70}. The owner passes these on.
    -- Donations recorded before this migration have no split (they went to the business).
    add column donation_split jsonb check (donation_split is null or jsonb_typeof(donation_split) = 'object');
