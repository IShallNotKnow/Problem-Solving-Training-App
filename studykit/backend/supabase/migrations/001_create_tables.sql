create table public.users (
  user_id uuid not null,
  email character varying(255) not null,
  created_at timestamp with time zone not null default now(),
  constraint users_pkey primary key (user_id),
  constraint users_email_key unique (email),
  constraint users_user_id_fkey foreign key (user_id) references auth.users(id) on delete cascade
) TABLESPACE pg_default;


create table public.sessions (
  session_id uuid not null default gen_random_uuid(),
  user_id uuid not null,
  created_at timestamp with time zone not null default now(),
  last_active_at timestamp with time zone not null default now(),
  current_question_index integer not null default 0,
  label text not null,
  constraint sessions_pkey primary key (session_id),
  constraint sessions_user_id_fkey foreign key (user_id) references users(user_id) on delete cascade
);
create index idx_sessions_user_id on public.sessions using btree (user_id);

CREATE TABLE public.elo_history (
  id uuid not null default gen_random_uuid(),
  session_id uuid not null,
  question_id text not null,
  topic text not null,
  previous_elo REAL not null,
  new_elo REAL not null,
  elo_delta REAL not null,
  previous_p_known REAL not null,
  new_p_known REAL not null,
  reason text not null,
  created_at timestamp with time zone not null default now(),
  constraint elo_history_pkey primary key (id),
  constraint elo_history_session_id_fkey foreign key (session_id) references sessions(session_id) on delete cascade
);
create index idx_elo_history_session_id on public.elo_history using btree (session_id);

CREATE TABLE public.generation_images (
  image_id uuid not null default gen_random_uuid(),
  session_id uuid not null,
  storage_path text not null,
  filename text not null,
  content_type text not null,
  description text null,
  constraint generation_images_pkey primary key (image_id),
  constraint generation_images_session_id_fkey foreign key (session_id) references sessions(session_id) on delete cascade
);
create index idx_generation_images_session_id on public.generation_images using btree (session_id);

create table public.generation_inputs (
  generation_input_id uuid not null default gen_random_uuid(),
  session_id uuid not null,
  content text not null default '',
  raw_markdown text not null default '',
  pdf_path text not null default '',
  questions_generated boolean not null default false,
  created_at timestamp with time zone not null default now(),
  constraint generation_inputs_pkey primary key (generation_input_id),
  constraint generation_inputs_session_id_fkey foreign key (session_id) references sessions(session_id) on delete cascade
);
create index idx_generation_inputs_session_id on public.generation_inputs using btree (session_id);

create table public.generation_topics (
  id uuid not null default gen_random_uuid(),
  generation_input_id uuid not null,
  topic text not null,
  constraint generation_topics_pkey primary key (id),
  constraint generation_topics_generation_input_id_fkey foreign key (generation_input_id) references generation_inputs(generation_input_id) on delete cascade
);
create index idx_generation_topics_generation_input_id on public.generation_topics using btree (generation_input_id);

create table public.topic_stats (
  id uuid not null default gen_random_uuid(),
  session_id uuid not null,
  topic text not null,
  attempts integer not null default 0,
  elo real not null default 800.0,
  p_known real not null default 0.5,
  constraint topic_stats_pkey primary key (id),
  constraint topic_stats_session_id_fkey foreign key (session_id) references sessions(session_id) on delete cascade,
  constraint topic_stats_session_topic_unique unique (session_id, topic)
);
create index idx_topic_stats_session_id on public.topic_stats using btree (session_id);

create table public.answer_attempts (
  attempt_id uuid not null default gen_random_uuid(),
  session_id uuid not null,
  question_id text not null,
  response text not null,
  score numeric(3, 2) not null,
  correct boolean not null,
  feedback text not null,
  misconception text null,
  answered_at timestamp with time zone not null default now(),
  constraint answer_attempts_pkey primary key (attempt_id),
  constraint answer_attempts_session_id_fkey foreign key (session_id) references sessions(session_id) on delete cascade,
  constraint answer_attempts_score_check check (score between 0.00 and 1.00)
) TABLESPACE pg_default;

create index idx_answer_attempts_session_id on public.answer_attempts using btree (session_id);

create table public.chat_messages (
  message_id uuid not null default gen_random_uuid(),
  session_id uuid not null,
  role text not null,
  content text not null,
  created_at timestamp with time zone not null default now(),
  constraint chat_messages_pkey primary key (message_id),
  constraint chat_messages_session_id_fkey foreign key (session_id) references sessions(session_id) on delete cascade,
  constraint chat_messages_role_check check (role = any (array['user'::text, 'assistant'::text]))
) TABLESPACE pg_default;

create index idx_chat_messages_session_id on public.chat_messages using btree (session_id);