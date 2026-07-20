create schema if not exists private;

revoke all on schema private from public, anon, authenticated;

create table if not exists private.ossys_api_hub_state (
    key text primary key,
    value jsonb not null,
    updated_at timestamptz not null default now()
);

alter table private.ossys_api_hub_state enable row level security;

revoke all on table private.ossys_api_hub_state from public, anon, authenticated;
