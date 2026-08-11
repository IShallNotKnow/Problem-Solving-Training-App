-- =============================================================================
-- ENABLE RLS
-- =============================================================================
ALTER TABLE sessions           ENABLE ROW LEVEL SECURITY;
ALTER TABLE study_sets         ENABLE ROW LEVEL SECURITY;
ALTER TABLE questions          ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_questions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE answer_attempts    ENABLE ROW LEVEL SECURITY;
ALTER TABLE topic_stats        ENABLE ROW LEVEL SECURITY;
ALTER TABLE elo_history        ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages      ENABLE ROW LEVEL SECURITY;
ALTER TABLE generation_inputs  ENABLE ROW LEVEL SECURITY;
ALTER TABLE generation_images  ENABLE ROW LEVEL SECURITY;
ALTER TABLE generation_topics  ENABLE ROW LEVEL SECURITY;
ALTER TABLE users              ENABLE ROW LEVEL SECURITY;


-- =============================================================================
-- SESSIONS
-- Used directly by appuser:
--   get()               [SELECT]
--   verify_ownership()  [SELECT]
--   create()            [INSERT]
--   create_study_set()  [UPDATE]
--   save()              [UPDATE]
--   finalize_generation [SELECT + UPDATE]
--
-- RPCs:
--   reset_session       [SECURITY DEFINER]
--   submit_answer       [SECURITY DEFINER]
--
-- appuser needs: SELECT, INSERT, UPDATE
-- No DELETE.
-- =============================================================================

CREATE POLICY "sessions_select_own"
ON sessions
FOR SELECT
TO appuser
USING (
    (select auth.uid()) = user_id
);

CREATE POLICY "sessions_insert_own"
ON sessions
FOR INSERT
TO appuser
WITH CHECK (
    (select auth.uid()) = user_id
);

CREATE POLICY "sessions_update_own"
ON sessions
FOR UPDATE
TO appuser
USING (
    (select auth.uid()) = user_id
)
WITH CHECK (
    (select auth.uid()) = user_id
);


-- =============================================================================
-- STUDY_SETS
-- Used directly by appuser:
--   verify_study_set_ownership() [SELECT]
--   create_study_set()           [INSERT]
--
-- appuser needs: SELECT, INSERT
-- No UPDATE/DELETE.
-- =============================================================================

CREATE POLICY "study_sets_select_own"
ON study_sets
FOR SELECT
TO appuser
USING (
    (select auth.uid()) = user_id
);

CREATE POLICY "study_sets_insert_own"
ON study_sets
FOR INSERT
TO appuser
WITH CHECK (
    (select auth.uid()) = user_id
);


-- =============================================================================
-- QUESTIONS
-- Used directly by appuser:
--   get()                [SELECT through session_questions relationship]
--   get_questions()      [SELECT through session_questions relationship]
--   upsert_questions...  [UPSERT = INSERT + UPDATE]
--
-- Ownership is through study_sets.user_id.
--
-- appuser needs: SELECT, INSERT, UPDATE
-- No DELETE.
-- =============================================================================

CREATE POLICY "questions_select_own"
ON questions
FOR SELECT
TO appuser
USING (
    EXISTS (
        SELECT 1
        FROM study_sets
        WHERE study_sets.study_set_id = questions.study_set_id
          AND study_sets.user_id = (select auth.uid())
    )
);

CREATE POLICY "questions_insert_own"
ON questions
FOR INSERT
TO appuser
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM study_sets
        WHERE study_sets.study_set_id = questions.study_set_id
          AND study_sets.user_id = (select auth.uid())
    )
);

CREATE POLICY "questions_update_own"
ON questions
FOR UPDATE
TO appuser
USING (
    EXISTS (
        SELECT 1
        FROM study_sets
        WHERE study_sets.study_set_id = questions.study_set_id
          AND study_sets.user_id = (select auth.uid())
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM study_sets
        WHERE study_sets.study_set_id = questions.study_set_id
          AND study_sets.user_id = (select auth.uid())
    )
);


-- =============================================================================
-- SESSION_QUESTIONS
-- Used directly by appuser:
--   get()                         [SELECT]
--   get_questions()               [SELECT]
--   populate_session_questions() [UPSERT = INSERT + UPDATE]
--
-- Ownership is through sessions.user_id.
--
-- appuser needs: SELECT, INSERT, UPDATE
-- No DELETE.
-- =============================================================================

CREATE POLICY "session_questions_select_own"
ON session_questions
FOR SELECT
TO appuser
USING (
    EXISTS (
        SELECT 1
        FROM sessions
        WHERE sessions.session_id = session_questions.session_id
          AND sessions.user_id = (select auth.uid())
    )
);

CREATE POLICY "session_questions_insert_own"
ON session_questions
FOR INSERT
TO appuser
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM sessions
        WHERE sessions.session_id = session_questions.session_id
          AND sessions.user_id = (select auth.uid())
    )
);

CREATE POLICY "session_questions_update_own"
ON session_questions
FOR UPDATE
TO appuser
USING (
    EXISTS (
        SELECT 1
        FROM sessions
        WHERE sessions.session_id = session_questions.session_id
          AND sessions.user_id = (select auth.uid())
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM sessions
        WHERE sessions.session_id = session_questions.session_id
          AND sessions.user_id = (select auth.uid())
    )
);


-- =============================================================================
-- ANSWER_ATTEMPTS
-- Used directly by appuser:
--   get() [SELECT]
--
-- submit_answer RPC performs INSERT as SECURITY DEFINER.
--
-- appuser needs: SELECT
-- =============================================================================

CREATE POLICY "answer_attempts_select_own"
ON answer_attempts
FOR SELECT
TO appuser
USING (
    EXISTS (
        SELECT 1
        FROM sessions
        WHERE sessions.session_id = answer_attempts.session_id
          AND sessions.user_id = (select auth.uid())
    )
);


-- =============================================================================
-- TOPIC_STATS
-- Used directly by appuser:
--   get() [SELECT]
--
-- submit_answer RPC performs UPSERT as SECURITY DEFINER.
-- save() no longer writes topic_stats.
--
-- appuser needs: SELECT only.
-- =============================================================================

CREATE POLICY "topic_stats_select_own"
ON topic_stats
FOR SELECT
TO appuser
USING (
    (select auth.uid()) = user_id
);


-- =============================================================================
-- ELO_HISTORY
-- Used directly by appuser:
--   get_topic_stats_at_question()    [SELECT]
--   get_topic_updates_for_question() [SELECT]
--   get_recent_topic_history()       [SELECT]
--   append_topic_updates()           [INSERT]
--
-- NOTE:
-- append_topic_updates() is a direct INSERT through appuser, not an RPC.
--
-- Ownership is through sessions.user_id.
--
-- appuser needs: SELECT, INSERT
-- =============================================================================

CREATE POLICY "elo_history_select_own"
ON elo_history
FOR SELECT
TO appuser
USING (
    EXISTS (
        SELECT 1
        FROM sessions
        WHERE sessions.session_id = elo_history.session_id
          AND sessions.user_id = (select auth.uid())
    )
);

CREATE POLICY "elo_history_insert_own"
ON elo_history
FOR INSERT
TO appuser
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM sessions
        WHERE sessions.session_id = elo_history.session_id
          AND sessions.user_id = (select auth.uid())
    )
);


-- =============================================================================
-- CHAT_MESSAGES
-- Used directly by appuser:
--   get()         [SELECT]
--   delete_chat() [DELETE]
--
-- append_chat_turn() is SECURITY DEFINER.
--
-- appuser needs: SELECT, DELETE
-- No INSERT.
-- =============================================================================

CREATE POLICY "chat_messages_select_own"
ON chat_messages
FOR SELECT
TO appuser
USING (
    EXISTS (
        SELECT 1
        FROM sessions
        WHERE sessions.session_id = chat_messages.session_id
          AND sessions.user_id = (select auth.uid())
    )
);

CREATE POLICY "chat_messages_delete_own"
ON chat_messages
FOR DELETE
TO appuser
USING (
    EXISTS (
        SELECT 1
        FROM sessions
        WHERE sessions.session_id = chat_messages.session_id
          AND sessions.user_id = (select auth.uid())
    )
);


-- =============================================================================
-- GENERATION_INPUTS
-- Used directly by appuser:
--   store_upload_context() [INSERT]
--   get_upload_context()   [SELECT]
--
-- finalize_generation() performs UPDATE directly through appuser.
--
-- Ownership is through study_sets.user_id.
--
-- appuser needs: SELECT, INSERT, UPDATE
-- =============================================================================

CREATE POLICY "generation_inputs_select_own"
ON generation_inputs
FOR SELECT
TO appuser
USING (
    EXISTS (
        SELECT 1
        FROM study_sets
        WHERE study_sets.study_set_id = generation_inputs.study_set_id
          AND study_sets.user_id = (select auth.uid())
    )
);

CREATE POLICY "generation_inputs_insert_own"
ON generation_inputs
FOR INSERT
TO appuser
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM study_sets
        WHERE study_sets.study_set_id = generation_inputs.study_set_id
          AND study_sets.user_id = (select auth.uid())
    )
);

CREATE POLICY "generation_inputs_update_own"
ON generation_inputs
FOR UPDATE
TO appuser
USING (
    EXISTS (
        SELECT 1
        FROM study_sets
        WHERE study_sets.study_set_id = generation_inputs.study_set_id
          AND study_sets.user_id = (select auth.uid())
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM study_sets
        WHERE study_sets.study_set_id = generation_inputs.study_set_id
          AND study_sets.user_id = (select auth.uid())
    )
);


-- =============================================================================
-- GENERATION_IMAGES
-- Used directly by appuser:
--   store_upload_context() [INSERT]
--
-- list_images() is service_role.
--
-- appuser needs: INSERT
-- No SELECT unless the application actually reads these rows using appuser.
-- =============================================================================

CREATE POLICY "generation_images_insert_own"
ON generation_images
FOR INSERT
TO appuser
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM generation_inputs
        JOIN study_sets
          ON study_sets.study_set_id = generation_inputs.study_set_id
        WHERE generation_inputs.generation_input_id =
              generation_images.generation_input_id
          AND study_sets.user_id = (select auth.uid())
    )
);


-- =============================================================================
-- GENERATION_TOPICS
-- Used directly by appuser:
--   get_relevant_profile() [SELECT]
--   finalize_generation() [INSERT]
--
-- Ownership is through generation_inputs -> study_sets -> user.
--
-- appuser needs: SELECT, INSERT
-- =============================================================================

CREATE POLICY "generation_topics_select_own"
ON generation_topics
FOR SELECT
TO appuser
USING (
    EXISTS (
        SELECT 1
        FROM generation_inputs
        JOIN study_sets
          ON study_sets.study_set_id = generation_inputs.study_set_id
        WHERE generation_inputs.generation_input_id =
              generation_topics.generation_input_id
          AND study_sets.user_id = (select auth.uid())
    )
);

CREATE POLICY "generation_topics_insert_own"
ON generation_topics
FOR INSERT
TO appuser
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM generation_inputs
        JOIN study_sets
          ON study_sets.study_set_id = generation_inputs.study_set_id
        WHERE generation_inputs.generation_input_id =
              generation_topics.generation_input_id
          AND study_sets.user_id = (select auth.uid())
    )
);


-- =============================================================================
-- USERS
-- Used only if the application directly accesses the users table through
-- the appuser role.
--
-- appuser needs: SELECT, INSERT, UPDATE
-- No DELETE yet.
-- =============================================================================

CREATE POLICY "users_select_own"
ON users
FOR SELECT
TO appuser
USING (
    (select auth.uid()) = user_id
);

CREATE POLICY "users_insert_own"
ON users
FOR INSERT
TO appuser
WITH CHECK (
    (select auth.uid()) = user_id
);

CREATE POLICY "users_update_own"
ON users
FOR UPDATE
TO appuser
USING (
    (select auth.uid()) = user_id
)
WITH CHECK (
    (select auth.uid()) = user_id
);