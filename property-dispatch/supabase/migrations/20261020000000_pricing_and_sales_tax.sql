-- Square-footage pricing and Texas sales tax on each booking.
-- amount_due stays the total the customer owes (price + tax), so payments
-- work as before; these columns record how it was calculated.
alter table jobs
    add column lawn_sqft  integer check (lawn_sqft between 100 and 200000),  -- mowing: lawn size priced on
    add column subtotal   numeric(8, 2) check (subtotal >= 0),                -- price before tax
    add column tax_rate   numeric(6, 5) check (tax_rate >= 0 and tax_rate < 0.2),
    add column tax_amount numeric(8, 2) check (tax_amount >= 0);

-- Existing bookings keep the price they were quoted (no tax added after the fact).
update jobs set subtotal = amount_due, tax_rate = 0, tax_amount = 0
 where subtotal is null and amount_due is not null;
