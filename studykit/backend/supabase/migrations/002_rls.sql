-- =============================================================================
-- ENABLE RLS (idempotent)
-- =============================================================================
 
ALTER TABLE sessions           ENABLE ROW LEVEL SECURITY;
ALTER TABLE questions          ENABLE ROW LEVEL SECURITY;
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
-- Used by: get(), verify_ownership(), create(), save(), reset_session (RPC),
--          submit_answer (RPC), replace_questions_and_finalize (RPC),
--          StorageManager.download_image() [service_role — bypasses RLS]
-- appuser needs: SELECT, INSERT, UPDATE
-- No DELETE — sessions are never deleted by the backend
-- =============================================================================
 
CREATE POLICY "sessions_select_own" ON sessions
    FOR SELECT TO appuser
    USING (auth.uid() = user_id);
 
CREATE POLICY "sessions_insert_own" ON sessions
    FOR INSERT TO appuser
    WITH CHECK (auth.uid() = user_id);
 
CREATE POLICY "sessions_update_own" ON sessions
    FOR UPDATE TO appuser
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "session_delete_own" ON sessions
    FOR DELETE TO appuser
    USING (auth.uid() = user_id);
 
 
-- =============================================================================
-- QUESTIONS
-- Used by: get() [SELECT], replace_questions_and_finalize RPC [DELETE+INSERT]
-- The RPC is SECURITY DEFINER so it bypasses RLS — appuser only needs SELECT.
-- =============================================================================
 
CREATE POLICY "questions_select_own" ON questions
    FOR SELECT TO appuser
    USING (
        EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = questions.session_id
              AND sessions.user_id = auth.uid()
        )
    );
 
 
-- =============================================================================
-- ANSWER_ATTEMPTS
-- Used by: get() [SELECT], submit_answer RPC [INSERT]
-- The RPC is SECURITY DEFINER — appuser only needs SELECT.
-- =============================================================================
 
CREATE POLICY "answer_attempts_select_own" ON answer_attempts
    FOR SELECT TO appuser
    USING (
        EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = answer_attempts.session_id
              AND sessions.user_id = auth.uid()
        )
    );
 
 
-- =============================================================================
-- TOPIC_STATS
-- Used by: get() [SELECT], save() [UPSERT], submit_answer RPC [UPSERT]
-- save() runs direct UPSERT via user client → needs INSERT + UPDATE.
-- submit_answer RPC is SECURITY DEFINER → covered by its own context.
-- =============================================================================
 
CREATE POLICY "topic_stats_select_own" ON topic_stats
    FOR SELECT TO appuser
    USING (
        EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = topic_stats.session_id
              AND sessions.user_id = auth.uid()
        )
    );
 
CREATE POLICY "topic_stats_insert_own" ON topic_stats
    FOR INSERT TO appuser
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = topic_stats.session_id
              AND sessions.user_id = auth.uid()
        )
    );
 
CREATE POLICY "topic_stats_update_own" ON topic_stats
    FOR UPDATE TO appuser
    USING (
        EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = topic_stats.session_id
              AND sessions.user_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = topic_stats.session_id
              AND sessions.user_id = auth.uid()
        )
    );
 
 
-- =============================================================================
-- ELO_HISTORY
-- Used by: get_topic_stats_at_question(), get_topic_updates_for_question(),
--          get_recent_topic_history() [all SELECT via user client]
--          submit_answer RPC [INSERT — SECURITY DEFINER, bypasses RLS]
-- appuser only needs SELECT.
-- =============================================================================
 
CREATE POLICY "elo_history_select_own" ON elo_history
    FOR SELECT TO appuser
    USING (
        EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = elo_history.session_id
              AND sessions.user_id = auth.uid()
        )
    );
 
 
-- =============================================================================
-- CHAT_MESSAGES
-- Used by: get() [SELECT], delete_chat() [DELETE],
--          append_chat_turn RPC [INSERT — SECURITY DEFINER, bypasses RLS]
-- appuser needs SELECT + DELETE only.
-- =============================================================================
 
CREATE POLICY "chat_messages_select_own" ON chat_messages
    FOR SELECT TO appuser
    USING (
        EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = chat_messages.session_id
              AND sessions.user_id = auth.uid()
        )
    );
 
CREATE POLICY "chat_messages_delete_own" ON chat_messages
    FOR DELETE TO appuser
    USING (
        EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = chat_messages.session_id
              AND sessions.user_id = auth.uid()
        )
    );
 
 
-- =============================================================================
-- GENERATION_INPUTS
-- Used by: store_upload_context() [INSERT], get_upload_context() [SELECT],
--          append_generation_input() [UPDATE],
--          replace_questions_and_finalize RPC [UPDATE — SECURITY DEFINER]
-- appuser needs SELECT, INSERT, UPDATE.
-- =============================================================================
 
CREATE POLICY "generation_inputs_select_own" ON generation_inputs
    FOR SELECT TO appuser
    USING (
        EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = generation_inputs.session_id
              AND sessions.user_id = auth.uid()
        )
    );
 
CREATE POLICY "generation_inputs_insert_own" ON generation_inputs
    FOR INSERT TO appuser
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = generation_inputs.session_id
              AND sessions.user_id = auth.uid()
        )
    );
 
CREATE POLICY "generation_inputs_update_own" ON generation_inputs
    FOR UPDATE TO appuser
    USING (
        EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = generation_inputs.session_id
              AND sessions.user_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = generation_inputs.session_id
              AND sessions.user_id = auth.uid()
        )
    );
 
 
-- =============================================================================
-- GENERATION_IMAGES
-- Used by: store_upload_context() [INSERT via user client],
--          StorageManager.list_images() [SELECT via service_role — bypasses RLS]
-- appuser needs SELECT + INSERT.
-- service_role bypasses RLS automatically — no policy needed for it.
-- =============================================================================
 
CREATE POLICY "generation_images_select_own" ON generation_images
    FOR SELECT TO appuser
    USING (
        EXISTS (
            SELECT 1 FROM generation_inputs
            JOIN sessions ON sessions.session_id = generation_inputs.session_id
            WHERE generation_inputs.generation_input_id = generation_images.generation_input_id
              AND sessions.user_id = auth.uid()
        )
    );
 
CREATE POLICY "generation_images_insert_own" ON generation_images
    FOR INSERT TO appuser
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM generation_inputs
            JOIN sessions ON sessions.session_id = generation_inputs.session_id
            WHERE generation_inputs.generation_input_id = generation_images.generation_input_id
              AND sessions.user_id = auth.uid()
        )
    );
 
 
-- =============================================================================
-- GENERATION_TOPICS
-- Used by: get_relevant_profile() [SELECT], append_generation_input() [INSERT],
--          replace_questions_and_finalize RPC [INSERT — SECURITY DEFINER]
-- appuser needs SELECT + INSERT.
-- =============================================================================
 
CREATE POLICY "generation_topics_select_own" ON generation_topics
    FOR SELECT TO appuser
    USING (
        EXISTS (
            SELECT 1 FROM generation_inputs
            JOIN sessions ON sessions.session_id = generation_inputs.session_id
            WHERE generation_inputs.generation_input_id = generation_topics.generation_input_id
              AND sessions.user_id = auth.uid()
        )
    );
 
CREATE POLICY "generation_topics_insert_own" ON generation_topics
    FOR INSERT TO appuser
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM generation_inputs
            JOIN sessions ON sessions.session_id = generation_inputs.session_id
            WHERE generation_inputs.generation_input_id = generation_topics.generation_input_id
              AND sessions.user_id = auth.uid()
        )
    );
 
 
-- =============================================================================
-- USERS
-- Standard self-ownership.
-- =============================================================================
 
CREATE POLICY "users_select_own" ON users
    FOR SELECT TO appuser USING (auth.uid() = user_id);
 
CREATE POLICY "users_insert_own" ON users
    FOR INSERT TO appuser WITH CHECK (auth.uid() = user_id);
 
CREATE POLICY "users_update_own" ON users
    FOR UPDATE TO appuser
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
 
 
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