-- =============================================================================
-- RPC FUNCTIONS — add SECURITY DEFINER so they bypass RLS internally.
-- This keeps appuser permissions minimal (no INSERT on questions/elo_history/
-- answer_attempts/chat_messages directly) while still enforcing ownership via
-- the session check inside each function.
--
-- IMPORTANT: each function must validate that the session belongs to the
-- calling user BEFORE mutating anything. The check below uses auth.uid()
-- which is available inside SECURITY DEFINER functions when called via the
-- Supabase user-scoped client (JWT is still present on the connection).
-- =============================================================================
 
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
    -- Ownership check: ensure caller owns this session
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
    SET current_question_index = 0,
        last_active_at = now()
    WHERE session_id = p_session_id;
END;
$$;
 
 
CREATE OR REPLACE FUNCTION replace_questions_and_finalize(
    p_session_id          UUID,
    p_questions           JSONB,
    p_generation_input_id UUID    DEFAULT NULL,
    p_topics_covered      JSONB   DEFAULT NULL,
    p_user_id             UUID DEFAULT NULL
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
        AND user_id = p_user_id
    ) THEN
        RAISE EXCEPTION 'session_not_found_or_forbidden';
    END IF;
 
    UPDATE sessions
    SET current_question_index = 0,
        questions_count        = jsonb_array_length(p_questions),
        last_active_at         = now()
    WHERE session_id = p_session_id;
 
    DELETE FROM questions WHERE session_id = p_session_id;
 
    INSERT INTO questions (
        session_id, question_id, position, question_type, prompt,
        choices, correct_choice_index, correct_answer, rubric_points,
        explanation, topic_difficulties
    )
    SELECT
        p_session_id,
        q->>'question_id',
        (q->>'position')::int,
        q->>'question_type',
        q->>'prompt',
        (q->'choices')::jsonb,
        (q->>'correct_choice_index')::int,
        q->>'correct_answer',
        (q->'rubric_points')::jsonb,
        q->>'explanation',
        (q->'topic_difficulties')::jsonb
    FROM jsonb_array_elements(p_questions) AS q;
 
    IF p_generation_input_id IS NOT NULL THEN
        UPDATE generation_inputs
        SET questions_generated = true
        WHERE generation_input_id = p_generation_input_id;
 
        INSERT INTO generation_topics (generation_input_id, topic)
        SELECT p_generation_input_id, t.value::text
        FROM jsonb_array_elements_text(p_topics_covered) AS t;
    END IF;
END;
$$;
 
 
CREATE OR REPLACE FUNCTION submit_answer(
    p_session_id   UUID,
    p_question_id  TEXT,
    p_response     TEXT,
    p_score        FLOAT,
    p_correct      BOOLEAN,
    p_feedback     TEXT,
    p_misconception TEXT,
    p_next_index   INT,
    p_topic_stats  JSONB,
    p_elo_history  JSONB
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
 
    INSERT INTO answer_attempts
        (session_id, question_id, response, score, correct, feedback, misconception)
    VALUES
        (p_session_id, p_question_id, p_response, p_score, p_correct, p_feedback, p_misconception);
 
    INSERT INTO elo_history
        (session_id, question_id, topic, previous_elo, new_elo, elo_delta,
         previous_p_known, new_p_known, reason)
    SELECT
        p_session_id,
        p_question_id,
        h->>'topic',
        (h->>'previous_elo')::int,
        (h->>'new_elo')::int,
        (h->>'elo_delta')::float,
        (h->>'previous_p_known')::float,
        (h->>'new_p_known')::float,
        h->>'reason'
    FROM jsonb_array_elements(p_elo_history) AS h;
 
    UPDATE sessions
    SET current_question_index = p_next_index,
        last_active_at         = now()
    WHERE session_id = p_session_id;
 
    INSERT INTO topic_stats (session_id, topic, elo, p_known, attempts)
    SELECT
        p_session_id,
        s->>'topic',
        (s->>'elo')::int,
        (s->>'p_known')::float,
        (s->>'attempts')::int
    FROM jsonb_array_elements(p_topic_stats) AS s
    ON CONFLICT (session_id, topic) DO UPDATE
        SET elo      = EXCLUDED.elo,
            p_known  = EXCLUDED.p_known,
            attempts = EXCLUDED.attempts;
END;
$$;