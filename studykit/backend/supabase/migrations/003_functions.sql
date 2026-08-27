CREATE OR REPLACE FUNCTION append_chat_turn(
    p_session_id UUID,
    p_user_content TEXT,
    p_assistant_content TEXT
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM sessions
        WHERE session_id = p_session_id
          AND user_id = auth.uid()
    ) THEN
        RAISE EXCEPTION 'session_not_found_or_forbidden';
    END IF;

    INSERT INTO chat_messages (session_id, role, content)
    VALUES
        (p_session_id, 'user',      p_user_content),
        (p_session_id, 'assistant', p_assistant_content);
END;
$$;


CREATE OR REPLACE FUNCTION reset_session(p_session_id UUID)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM sessions
        WHERE session_id = p_session_id
          AND user_id = auth.uid()
    ) THEN
        RAISE EXCEPTION 'session_not_found' USING DETAIL = p_session_id::text;
    END IF;

    UPDATE sessions
    SET current_position = 0,
        last_active_at   = now()
    WHERE session_id = p_session_id;

    -- Reset all session_questions back to unseen so the session can be replayed
    UPDATE session_questions
    SET status = 'unseen'
    WHERE session_id = p_session_id;
END;
$$;


CREATE OR REPLACE FUNCTION submit_answer(
    p_session_id    UUID,
    p_user_id       UUID,
    p_question_id   UUID,
    p_response      TEXT,
    p_score         FLOAT,
    p_correct       BOOLEAN,
    p_feedback      TEXT,
    p_misconception TEXT,
    p_next_position INT,
    p_topic_stats   JSONB,
    p_elo_history   JSONB,
    p_topic_misconceptions   JSONB, 
    p_stability     FLOAT,
    p_difficulty    FLOAT,
    p_due_at        TIMESTAMPTZ
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM sessions
        WHERE session_id = p_session_id
          AND user_id    = p_user_id
          AND p_user_id  = auth.uid()
    ) THEN
        RAISE EXCEPTION 'session_not_found_or_forbidden';
    END IF;

    INSERT INTO answer_attempts
        (session_id, question_id, response, score, correct, feedback, misconception, topic_misconceptions)
    VALUES
        (p_session_id, p_question_id, p_response, p_score, p_correct, p_feedback, p_misconception, p_topic_misconceptions);

    INSERT INTO elo_history
        (session_id, question_id, topic, previous_elo, new_elo, elo_delta,
         previous_p_known, new_p_known, reason)
    SELECT
        p_session_id,
        p_question_id,
        h->>'topic',
        (h->>'previous_elo')::smallint,
        (h->>'new_elo')::smallint,
        (h->>'elo_delta')::float,
        (h->>'previous_p_known')::float,
        (h->>'new_p_known')::float,
        h->>'reason'
    FROM jsonb_array_elements(p_elo_history) AS h;

    UPDATE sessions
    SET current_position = p_next_position,
        last_active_at   = now()
    WHERE session_id = p_session_id;

    UPDATE session_questions
    SET status = 'active'
    WHERE session_id  = p_session_id
      AND question_id = p_question_id;

    -- Single upsert handles both first attempt and subsequent updates
    INSERT INTO question_scheduling
        (user_id, question_id, stability, difficulty, due_at, times_seen, last_attempted_at)
    VALUES
        (p_user_id, p_question_id, p_stability, p_difficulty, p_due_at, 1, now())
    ON CONFLICT (user_id, question_id) DO UPDATE
        SET stability         = EXCLUDED.stability,
            difficulty        = EXCLUDED.difficulty,
            due_at            = EXCLUDED.due_at,
            times_seen        = question_scheduling.times_seen + 1,
            last_attempted_at = now();

    INSERT INTO topic_stats (user_id, topic, elo, p_known, attempts)
    SELECT
        p_user_id,
        s->>'topic',
        (s->>'elo')::smallint,
        (s->>'p_known')::float,
        (s->>'attempts')::int
    FROM jsonb_array_elements(p_topic_stats) AS s
    ON CONFLICT (user_id, topic) DO UPDATE
        SET elo      = EXCLUDED.elo,
            p_known  = EXCLUDED.p_known,
            attempts = EXCLUDED.attempts;
END;
$$;

-- Replaces replace_questions_and_finalize — questions now live in study sets,
-- session_questions is the join table, finalization links session to study set
CREATE OR REPLACE FUNCTION finalize_generation(
    p_session_id          UUID,
    p_user_id             UUID,
    p_study_set_id        UUID,
    p_generation_input_id UUID DEFAULT NULL,
    p_topics_covered      JSONB DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM sessions
        WHERE session_id = p_session_id
          AND user_id    = p_user_id
    ) THEN
        RAISE EXCEPTION 'session_not_found_or_forbidden';
    END IF;

    -- Link session to study set and reset position for new question queue
    UPDATE sessions
    SET study_set_id     = p_study_set_id,
        current_position = 0,
        last_active_at   = now()
    WHERE session_id = p_session_id;

    IF p_generation_input_id IS NOT NULL THEN
        UPDATE generation_inputs
        SET questions_generated = true,
            status              = 'completed'
        WHERE generation_input_id = p_generation_input_id;

        IF p_topics_covered IS NOT NULL THEN
            INSERT INTO generation_topics (generation_input_id, topic)
            SELECT p_generation_input_id, t.value::text
            FROM jsonb_array_elements_text(p_topics_covered) AS t;
        END IF;
    END IF;
END;
$$;


-- Resurfacing candidates — reads from question_scheduling for due dates,
-- joins through study_sets to scope to the right pool
CREATE OR REPLACE FUNCTION get_resurfacing_candidates(p_study_set_id UUID)
RETURNS TABLE (
    id                   UUID,
    question_id          TEXT,
    study_set_id         UUID,
    generation_input_id  UUID,
    question_type        TEXT,
    prompt               TEXT,
    correct_answer       TEXT,
    explanation          TEXT,
    topic_difficulties   JSONB,
    choices              JSONB,
    correct_choice_index INTEGER,
    rubric_points        JSONB,
    last_attempted_at    TIMESTAMP WITH TIME ZONE,
    times_seen           INTEGER,
    topics               TEXT[]
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT
        q.id,
        q.question_id,
        q.study_set_id,
        q.generation_input_id,
        q.question_type,
        q.prompt,
        q.correct_answer,
        q.explanation,
        q.topic_difficulties,
        q.choices,
        q.correct_choice_index,
        q.rubric_points,
        qs.last_attempted_at,
        COALESCE(qs.times_seen, 0)::integer,
        ARRAY(
            SELECT jsonb_object_keys(q.topic_difficulties)
        ) AS topics
    FROM questions q
    LEFT JOIN question_scheduling qs
        ON qs.question_id = q.id
        AND qs.user_id    = auth.uid()
    WHERE q.study_set_id = p_study_set_id
      AND qs.last_attempted_at IS NOT NULL  -- only questions already seen
      AND (
          qs.due_at IS NULL
          OR qs.due_at <= now()
      );
END;
$$;

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.users (user_id, email, created_at)
    VALUES (NEW.id, NEW.email, NOW())
    ON CONFLICT (user_id) DO NOTHING;
    RETURN NEW;
END;
$$;