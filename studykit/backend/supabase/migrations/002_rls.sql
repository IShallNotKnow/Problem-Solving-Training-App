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

CREATE POLICY "sessions_delete_own"
ON sessions
FOR DELETE
TO appuser
USING (
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
        JOIN study_sets ON study_sets.study_set_id = generation_inputs.study_set_id
        WHERE generation_inputs.generation_input_id = generation_images.generation_input_id
        AND study_sets.user_id = (SELECT auth.uid())
    )
);

CREATE POLICY "generation_images_select_own"
ON generation_images
FOR SELECT
TO appuser
USING (
    EXISTS (
        SELECT 1
        FROM generation_inputs
        JOIN study_sets ON study_sets.study_set_id = generation_inputs.study_set_id
        WHERE generation_inputs.generation_input_id = generation_images.generation_input_id
        AND study_sets.user_id = (SELECT auth.uid())
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

-- Trigger fires after every new signup in auth.users
CREATE OR REPLACE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();

-- =============================================================================
-- STORAGE BUCKET POLICIES
-- StorageManager always uses service_role, which bypasses RLS by default.
-- These policies make that restriction explicit and block all other roles.
-- =============================================================================
 
-- generation-pdfs: service_role only (store_pdf writes, no reads from backend)
CREATE POLICY "pdfs_insert_service_only" ON storage.objects
    FOR INSERT TO service_role
    WITH CHECK (bucket_id = 'generation-pdfs');
 
CREATE POLICY "pdfs_select_service_only" ON storage.objects
    FOR SELECT TO service_role
    USING (bucket_id = 'generation-pdfs');
 
-- generation-images: service_role only (store_images writes, download_image reads)
CREATE POLICY "images_insert_service_only" ON storage.objects
    FOR INSERT TO service_role
    WITH CHECK (bucket_id = 'generation-images');
 
CREATE POLICY "images_select_service_only" ON storage.objects
    FOR SELECT TO service_role
    USING (bucket_id = 'generation-images');

GRANT SELECT ON public.generation_images TO service_role;
GRANT SELECT ON public.generation_inputs TO service_role;
GRANT SELECT ON public.study_sets TO service_role;

-- Grant appuser access to the tables it needs
GRANT USAGE ON SCHEMA public TO appuser;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.users TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.sessions TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.study_sets TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.generation_inputs TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.generation_topics TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.generation_images TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.questions TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.question_scheduling TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.session_questions TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.answer_attempts TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.elo_history TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.topic_stats TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.chat_messages TO appuser;

-- Grant execute on RPCs so appuser can call them
GRANT EXECUTE ON FUNCTION public.append_chat_turn(UUID, TEXT, TEXT) TO appuser;
GRANT EXECUTE ON FUNCTION public.reset_session(UUID) TO appuser;
GRANT EXECUTE ON FUNCTION public.submit_answer(UUID, UUID, UUID, TEXT, FLOAT, BOOLEAN, TEXT, TEXT, INT, JSONB, JSONB) TO appuser;
GRANT EXECUTE ON FUNCTION public.finalize_generation(UUID, UUID, UUID, UUID, JSONB) TO appuser;
GRANT EXECUTE ON FUNCTION public.get_resurfacing_candidates(UUID) TO appuser;
GRANT EXECUTE ON FUNCTION public.handle_new_user() TO appuser;

-- Sequences for any serial/generated columns
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO appuser;

-- Ensure future tables and sequences are also granted
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO appuser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO appuser;