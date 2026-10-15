-- One row per day. MetricFlow needs a time spine to resolve metric_time.
select date_day
from unnest(generate_date_array(date '2026-01-01', date '2026-12-31')) as date_day
