drop table if exists public.question_scheduling cascade;
drop table if exists public.answer_attempts cascade;
drop table if exists public.chat_messages cascade;
drop table if exists public.elo_history cascade;
drop table if exists public.topic_stats cascade;
drop table if exists public.session_questions cascade;
drop table if exists public.study_sessions cascade;
drop table if exists public.generation_topics cascade;
drop table if exists public.generation_images cascade;
drop table if exists public.questions cascade;
drop table if exists public.generation_inputs cascade;
drop table if exists public.study_sets cascade;
drop table if exists public.sessions cascade;
drop table if exists public.users cascade;

-- users
create table public.users (
  user_id    uuid not null,
  email      character varying(255) not null,
  created_at timestamp with time zone not null default now(),
  constraint users_pkey primary key (user_id),
  constraint users_email_key unique (email),
  constraint users_user_id_fkey foreign key (user_id)
    references auth.users (id) on delete cascade
) tablespace pg_default;

-- sessions (study sessions — one per sitting)
create table public.sessions (
  session_id     uuid not null default gen_random_uuid(),
  user_id        uuid not null,
  study_set_id   uuid, --careful with how this is passed/handled
  label          text not null,
  created_at     timestamp with time zone not null default now(),
  last_active_at timestamp with time zone not null default now(),
  current_position integer not null default 0,
  constraint sessions_pkey primary key (session_id),
  constraint sessions_user_id_fkey foreign key (user_id)
    references public.users (user_id) on delete cascade
) tablespace pg_default;

create index idx_sessions_user_id
  on public.sessions using btree (user_id) tablespace pg_default;
create index idx_sessions_last_active
  on public.sessions using btree (last_active_at desc) tablespace pg_default;

-- study_sets — a collection of source material and its generated questions
create table public.study_sets (
  study_set_id uuid not null default gen_random_uuid(),
  user_id      uuid not null,
  label        text not null,
  created_at   timestamp with time zone not null default now(),
  constraint study_sets_pkey primary key (study_set_id),
  constraint study_sets_user_id_fkey foreign key (user_id)
    references public.users (user_id) on delete cascade
) tablespace pg_default;

create index idx_study_sets_user_id
  on public.study_sets using btree (user_id) tablespace pg_default;

-- generation_inputs — source material for one generation run
create table public.generation_inputs (
  generation_input_id uuid not null default gen_random_uuid(),
  study_set_id        uuid not null,
  content             text not null default '',
  raw_markdown        text not null default '',
  pdf_path            text not null default '',
  questions_generated boolean not null default false,
  status              text not null default 'in_progress',
  created_at          timestamp with time zone not null default now(),
  constraint generation_inputs_pkey primary key (generation_input_id),
  constraint generation_inputs_study_set_id_fkey foreign key (study_set_id)
    references public.study_sets (study_set_id) on delete cascade,
  constraint generation_inputs_status_check check (
    status = any (array['in_progress'::text, 'completed'::text, 'failed'::text])
  )
) tablespace pg_default;

create index idx_generation_inputs_study_set_id
  on public.generation_inputs using btree (study_set_id) tablespace pg_default;

-- generation_topics — topic coverage per generation run
create table public.generation_topics (
  id                  uuid not null default gen_random_uuid(),
  generation_input_id uuid not null,
  topic               text not null,
  constraint generation_topics_pkey primary key (id),
  constraint generation_topics_generation_input_id_fkey foreign key (generation_input_id)
    references public.generation_inputs (generation_input_id) on delete cascade
) tablespace pg_default;

create index idx_generation_topics_generation_input_id
  on public.generation_topics using btree (generation_input_id) tablespace pg_default;

-- generation_images — images extracted from a generation run
create table public.generation_images (
  image_id            uuid not null default gen_random_uuid(),
  generation_input_id uuid not null,
  storage_path        text not null,
  filename            text not null,
  content_type        text not null,
  description         text null,
  constraint generation_images_pkey primary key (image_id),
  constraint generation_images_generation_input_id_fkey foreign key (generation_input_id)
    references public.generation_inputs (generation_input_id) on delete cascade
) tablespace pg_default;

create index idx_generation_images_generation_input_id
  on public.generation_images using btree (generation_input_id) tablespace pg_default;

-- questions — persistent content pool owned by a study set
create table public.questions (
  id                   uuid not null default gen_random_uuid(),
  study_set_id         uuid not null,
  generation_input_id  uuid null,
  question_id          text not null,
  question_type        text not null,
  prompt               text not null,
  correct_answer       text not null,
  explanation          text not null,
  topic_difficulties   jsonb not null,
  choices              jsonb null,
  correct_choice_index integer null,
  rubric_points        jsonb null,
  constraint questions_pkey primary key (id),
  constraint questions_study_set_generation_question_unique
    unique (study_set_id, generation_input_id, question_id),
  constraint questions_study_set_id_fkey foreign key (study_set_id)
    references public.study_sets (study_set_id) on delete cascade,
  constraint questions_generation_input_id_fkey foreign key (generation_input_id)
    references public.generation_inputs (generation_input_id) on delete set null,
  constraint questions_question_type_check check (
    question_type = any (array['MCQ'::text, 'FRQ'::text])
  )
) tablespace pg_default;

create index idx_questions_study_set_id
  on public.questions using btree (study_set_id) tablespace pg_default;
create index idx_questions_generation_input_id
  on public.questions using btree (generation_input_id) tablespace pg_default;

-- question_scheduling — FSRS state per user-question pair
-- this is the scheduler's persistent state, separate from question content
create table public.question_scheduling (
  id            uuid not null default gen_random_uuid(),
  user_id       uuid not null,
  question_id   uuid not null,
  due_at        timestamp with time zone null,
  stability     real not null default 0.0,
  difficulty    real not null default 0.3,
  retrievability real not null default 1.0,
  times_seen    integer not null default 0,
  last_attempted_at timestamp with time zone null,
  constraint question_scheduling_pkey primary key (id),
  constraint question_scheduling_user_question_unique unique (user_id, question_id),
  constraint question_scheduling_user_id_fkey foreign key (user_id)
    references public.users (user_id) on delete cascade,
  constraint question_scheduling_question_id_fkey foreign key (question_id)
    references public.questions (id) on delete cascade
) tablespace pg_default;

create index idx_question_scheduling_user_id
  on public.question_scheduling using btree (user_id) tablespace pg_default;
create index idx_question_scheduling_due_at
  on public.question_scheduling using btree (user_id, due_at asc nulls first) tablespace pg_default;

-- session_questions — scheduler's selection for one study session
create table public.session_questions (
  id          uuid not null default gen_random_uuid(),
  session_id  uuid not null,
  question_id uuid not null,
  position    integer not null,
  source      text not null default 'generated',
  status      text not null default 'unseen',
  constraint session_questions_pkey primary key (id),
  constraint session_questions_session_question_unique unique (session_id, question_id),
  constraint session_questions_session_id_fkey foreign key (session_id)
    references public.sessions (session_id) on delete cascade,
  constraint session_questions_question_id_fkey foreign key (question_id)
    references public.questions (id) on delete cascade,
  constraint session_questions_source_check check (
    source = any (array['generated'::text, 'resurfaced'::text])
  ),
  constraint session_questions_status_check check (
    status = any (array['unseen'::text, 'active'::text, 'mastered'::text, 'due'::text])
  )
) tablespace pg_default;

create index idx_session_questions_session_id
  on public.session_questions using btree (session_id) tablespace pg_default;
create index idx_session_questions_position
  on public.session_questions using btree (session_id, position) tablespace pg_default;

-- answer_attempts — interaction records tied to session + question
create table public.answer_attempts (
  attempt_id    uuid not null default gen_random_uuid(),
  session_id    uuid not null,
  question_id   uuid not null,
  response      text not null,
  score         numeric(3, 2) not null,
  correct       boolean not null,
  feedback      text not null,
  misconception text null,
  answered_at   timestamp with time zone not null default now(),
  constraint answer_attempts_pkey primary key (attempt_id),
  constraint answer_attempts_session_id_fkey foreign key (session_id)
    references public.sessions (session_id) on delete cascade,
  constraint answer_attempts_question_id_fkey foreign key (question_id)
    references public.questions (id) on delete cascade,
  constraint answer_attempts_score_check check (score between 0.00 and 1.00)
) tablespace pg_default;

create index idx_answer_attempts_session_id
  on public.answer_attempts using btree (session_id) tablespace pg_default;
create index idx_answer_attempts_question_id
  on public.answer_attempts using btree (question_id) tablespace pg_default;

-- chat_messages — tied to session interaction
create table public.chat_messages (
  message_id uuid not null default gen_random_uuid(),
  session_id uuid not null,
  role       text not null,
  content    text not null,
  created_at timestamp with time zone not null default now(),
  constraint chat_messages_pkey primary key (message_id),
  constraint chat_messages_session_id_fkey foreign key (session_id)
    references public.sessions (session_id) on delete cascade,
  constraint chat_messages_role_check check (
    role = any (array['user'::text, 'assistant'::text])
  )
) tablespace pg_default;

create index idx_chat_messages_session_id
  on public.chat_messages using btree (session_id) tablespace pg_default;

-- topic_stats — currently session-scoped, move to user-scoped when ready
-- keeping session_id for now to avoid breaking the ELO/BKT update logic
create table public.topic_stats (
  id         uuid not null default gen_random_uuid(),
  user_id    uuid not null,
  topic      text not null,
  attempts   integer not null default 0,
  elo        smallint not null default 800,
  p_known    real not null default 0.5,
  constraint topic_stats_pkey primary key (id),
  constraint topic_stats_user_topic_unique unique (user_id, topic),
  constraint topic_stats_user_id_fkey foreign key (user_id)
    references public.users (user_id) on delete cascade,
  constraint topic_stats_elo_check check (elo >= 300 and elo <= 3000)
) tablespace pg_default;

create index idx_topic_stats_user_id
  on public.topic_stats using btree (user_id) tablespace pg_default;

-- elo_history — interaction record, session-scoped
create table public.elo_history (
  id               uuid not null default gen_random_uuid(),
  session_id       uuid not null,
  question_id      uuid not null,
  topic            text not null,
  previous_elo     smallint not null,
  new_elo          smallint not null,
  elo_delta        real not null,
  previous_p_known real not null,
  new_p_known      real not null,
  reason           text not null,
  created_at       timestamp with time zone not null default now(),
  constraint elo_history_pkey primary key (id),
  constraint elo_history_session_id_fkey foreign key (session_id)
    references public.sessions (session_id) on delete cascade,
  constraint elo_history_question_id_fkey foreign key (question_id)
    references public.questions (id) on delete cascade,
  constraint elo_history_new_elo_check check (new_elo >= 300 and new_elo <= 3000),
  constraint elo_history_previous_elo_check check (previous_elo >= 300 and previous_elo <= 3000)
) tablespace pg_default;

create index idx_elo_history_session_id
  on public.elo_history using btree (session_id) tablespace pg_default;
create index idx_elo_history_question_id
  on public.elo_history using btree (question_id) tablespace pg_default;
create index idx_elo_history_topic_time
  on public.elo_history using btree (session_id, topic, created_at desc) tablespace pg_default;