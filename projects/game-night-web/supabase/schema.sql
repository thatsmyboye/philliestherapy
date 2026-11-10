-- Game Night web app schema. Run once in the Supabase SQL editor.
-- Every table is prefixed gn_ so it sits beside the bot's kv_store without overlap.
-- The app talks to these with the service_role key (bypasses RLS). RLS is on
-- everywhere; the only thing the public anon key can read is gn_live.

create extension if not exists pgcrypto;

create table if not exists gn_users (
    id                        uuid primary key default gen_random_uuid(),
    patreon_user_id           text not null unique,
    patreon_name              text,
    tier                      int  not null default 0,   -- 0 free, 1 member ($5), 2 producer ($12), 3 exec producer ($25)
    patron_status             text,
    entitled_cents            int  not null default 0,
    tier_checked_at           timestamptz,
    patreon_refresh_token_enc text,
    discord_user_id           text unique,
    discord_username          text,
    discord_in_guild          boolean not null default false,
    discord_linked_at         timestamptz,
    display_name              text,
    created_at                timestamptz not null default now(),
    last_login_at             timestamptz not null default now()
);

create table if not exists gn_episodes (
    id          serial primary key,
    season      text not null,
    number      int  not null,
    title       text not null,
    theme       text,
    airs_at     timestamptz,
    status      text not null default 'upcoming',  -- upcoming | live | done
    exec_seats  int  not null default 1,           -- guaranteed Executive Producer seats; 0 = none (championship)
    unique (season, number)
);

create table if not exists gn_seat_claims (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references gn_users(id) on delete cascade,
    episode_id  int  not null references gn_episodes(id) on delete cascade,
    season      text not null,
    created_at  timestamptz not null default now(),
    unique (user_id, season)                       -- one guaranteed seat per offseason
);
create index if not exists gn_seat_claims_episode on gn_seat_claims(episode_id);

-- Single row (id = 1) mirroring what the overlay is showing right now.
-- `answer` is null until the host reveals it on stream.
create table if not exists gn_live (
    id              int primary key default 1 check (id = 1),
    status          text not null default 'idle',  -- idle | open | closed | revealed
    episode_number  int,
    episode_title   text,
    question_id     text,
    category        text,
    difficulty      text,
    question        text,
    answer          text,
    opens_at        timestamptz,
    closes_at       timestamptz,
    first_correct   text,                          -- display name of the Bullpen scorer
    updated_at      timestamptz not null default now()
);
insert into gn_live (id) values (1) on conflict do nothing;

create table if not exists gn_swings (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null references gn_users(id) on delete cascade,
    season          text not null,
    episode_number  int  not null,
    question_id     text not null,
    answer          text not null,
    correct         boolean,                       -- null until graded at the reveal
    points          int  not null default 0,
    created_at      timestamptz not null default now(),
    unique (user_id, season, episode_number, question_id)  -- one final answer
);
create index if not exists gn_swings_question on gn_swings(season, episode_number, question_id);

create table if not exists gn_standings (
    season      text not null,
    name        text not null,
    wins        int  not null default 0,
    runs        int  not null default 0,
    potg        int  not null default 0,
    points      int  not null default 0,
    updated_at  timestamptz not null default now(),
    primary key (season, name)
);

alter table gn_users        enable row level security;
alter table gn_episodes     enable row level security;
alter table gn_seat_claims  enable row level security;
alter table gn_live         enable row level security;
alter table gn_swings       enable row level security;
alter table gn_standings    enable row level security;

drop policy if exists gn_live_public_read on gn_live;
create policy gn_live_public_read on gn_live for select to anon, authenticated using (true);

-- Push gn_live changes to browsers on /play.
do $$
begin
    if not exists (
        select 1 from pg_publication_tables
        where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'gn_live'
    ) then
        alter publication supabase_realtime add table gn_live;
    end if;
end $$;

-- Claim an Executive Producer seat. Serialised per episode so two members
-- cannot both take the last seat. Returns 'ok', 'full', 'already', or 'closed'.
create or replace function gn_claim_seat(p_user uuid, p_episode int)
returns text
language plpgsql
set search_path = public
as $$
declare
    ep      gn_episodes%rowtype;
    taken   int;
begin
    select * into ep from gn_episodes where id = p_episode for update;
    if not found or ep.status <> 'upcoming' or ep.exec_seats <= 0 then
        return 'closed';
    end if;
    if exists (select 1 from gn_seat_claims where user_id = p_user and season = ep.season) then
        return 'already';
    end if;
    select count(*) into taken from gn_seat_claims where episode_id = p_episode;
    if taken >= ep.exec_seats then
        return 'full';
    end if;
    insert into gn_seat_claims (user_id, episode_id, season) values (p_user, p_episode, ep.season);
    return 'ok';
end $$;
revoke all on function gn_claim_seat(uuid, int) from public, anon, authenticated;
grant execute on function gn_claim_seat(uuid, int) to service_role;

-- Hot Stove League, per the rulebook. Dates are set from /admin.
insert into gn_episodes (season, number, title, theme, exec_seats) values
    ('2026-27', 1, 'Hot Stove Premiere',      'Winter Meetings week',                         1),
    ('2026-27', 2, 'Hall of Fame Week',       'Franchise History and Postseason',             1),
    ('2026-27', 3, 'Spring Training Preview', 'Around the League and Connections',            1),
    ('2026-27', 4, 'Championship',            'Top three from Episodes 1-3. Opening Day eve.', 0)
on conflict (season, number) do nothing;
