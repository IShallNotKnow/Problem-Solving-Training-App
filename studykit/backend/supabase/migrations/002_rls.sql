ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE answer_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE topic_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE elo_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE generation_inputs ENABLE ROW LEVEL SECURITY;
ALTER TABLE generation_images ENABLE ROW LEVEL SECURITY;
ALTER TABLE generation_topics ENABLE ROW LEVEL SECURITY;

-- sessions: user owns their own rows
CREATE POLICY "users_own_sessions" ON sessions
    FOR ALL USING (auth.uid() = user_id);

-- everything else: accessible if the parent session belongs to the user
CREATE POLICY "users_own_questions" ON questions
    FOR ALL USING (
        EXISTS (SELECT 1 FROM sessions WHERE sessions.session_id = questions.session_id AND sessions.user_id = auth.uid())
    );

CREATE POLICY "users_own_answer_attempts" ON answer_attempts
    FOR ALL USING (
        EXISTS (SELECT 1 FROM sessions WHERE sessions.session_id = answer_attempts.session_id AND sessions.user_id = auth.uid())
    );

CREATE POLICY "users_own_topic_stats" ON topic_stats
    FOR ALL USING (
        EXISTS (SELECT 1 FROM sessions WHERE sessions.session_id = topic_stats.session_id AND sessions.user_id = auth.uid())
    );

CREATE POLICY "users_own_elo_history" ON elo_history
    FOR ALL USING (
        EXISTS (SELECT 1 FROM sessions WHERE sessions.session_id = elo_history.session_id AND sessions.user_id = auth.uid())
    );

CREATE POLICY "users_own_chat_messages" ON chat_messages
    FOR ALL USING (
        EXISTS (SELECT 1 FROM sessions WHERE sessions.session_id = chat_messages.session_id AND sessions.user_id = auth.uid())
    );

CREATE POLICY "users_own_generation_inputs" ON generation_inputs
    FOR ALL USING (
        EXISTS (SELECT 1 FROM sessions WHERE sessions.session_id = generation_inputs.session_id AND sessions.user_id = auth.uid())
    );

-- generation_images and generation_topics join through generation_inputs
CREATE POLICY "users_own_generation_images" ON generation_images
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM generation_inputs
            JOIN sessions ON sessions.session_id = generation_inputs.session_id
            WHERE generation_inputs.generation_input_id = generation_images.generation_input_id
            AND sessions.user_id = auth.uid()
        )
    );

CREATE POLICY "users_own_generation_topics" ON generation_topics
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM generation_inputs
            JOIN sessions ON sessions.session_id = generation_inputs.session_id
            WHERE generation_inputs.generation_input_id = generation_topics.generation_input_id
            AND sessions.user_id = auth.uid()
        )
    );

CREATE POLICY "sessions_select_own" ON sessions
FOR SELECT TO appuser USING (auth.uid() = user_id);

CREATE POLICY "sessions_insert_own" ON sessions
FOR INSERT TO appuser WITH CHECK (auth.uid() = user_id);

CREATE POLICY "sessions_update_own" ON sessions
FOR UPDATE TO appuser
USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "sessions_delete_own" ON sessions
FOR DELETE TO appuser USING (auth.uid() = user_id);


CREATE POLICY "chat_messages_select_own" ON chat_messages
FOR SELECT TO appuser USING (
    EXISTS (
        SELECT 1 FROM sessions
        WHERE sessions.session_id = chat_messages.session_id
        AND sessions.user_id = auth.uid()
    )
);

CREATE POLICY "chat_messages_delete_own" ON chat_messages
FOR DELETE TO appuser USING (
    EXISTS (
        SELECT 1 FROM sessions
        WHERE sessions.session_id = chat_messages.session_id
        AND sessions.user_id = auth.uid()
    )
);


CREATE POLICY "answer_attempts_select_own" ON answer_attempts
FOR SELECT TO appuser USING (
    EXISTS (
        SELECT 1 FROM sessions
        WHERE sessions.session_id = answer_attempts.session_id
        AND sessions.user_id = auth.uid()
    )
);


-- buckets
create policy "service role only upload pdf"
on storage.objects for insert
to service_role
with check (bucket_id = 'generation-pdfs');

create policy "service role only read pdf"
on storage.objects for select
to service_role
using (bucket_id = 'generation-pdfs');

-- generation-images
create policy "service role only upload image"
on storage.objects for insert
to service_role
with check (bucket_id = 'generation-images');

create policy "service role only read image"
on storage.objects for select
to service_role
using (bucket_id = 'generation-images');

-- questions
CREATE POLICY "questions_insert_service" ON questions
FOR INSERT TO appuser WITH CHECK (
    EXISTS (
        SELECT 1 FROM sessions
        WHERE sessions.session_id = topic_stats.session_id
        AND sessions.user_id = auth.uid()
    )
);

CREATE POLICY "questions_delete_service" ON questions
FOR DELETE TO appuser USING (
    EXISTS (
        SELECT 1 FROM sessions
        WHERE sessions.session_id = chat_messages.session_id
        AND sessions.user_id = auth.uid()
    )
);

-- topic_stats
ALTER TABLE topic_stats ENABLE ROW LEVEL SECURITY;

CREATE POLICY "topic_stats_select_own" ON topic_stats
FOR SELECT TO appuser USING (
    EXISTS (
        SELECT 1 FROM sessions
        WHERE sessions.session_id = topic_stats.session_id
        AND sessions.user_id = auth.uid()
    )
);

CREATE POLICY "topic_stats_insert_service" ON topic_stats
FOR INSERT TO service_role WITH CHECK (true);

CREATE POLICY "topic_stats_update_service" ON topic_stats
FOR UPDATE TO service_role USING (true) WITH CHECK (true);

-- elo_history
ALTER TABLE elo_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "elo_history_select_own" ON elo_history
FOR SELECT TO appuser USING (
    EXISTS (
        SELECT 1 FROM sessions
        WHERE sessions.session_id = elo_history.session_id
        AND sessions.user_id = auth.uid()
    )
);

CREATE POLICY "elo_history_insert_service" ON elo_history
FOR INSERT TO service_role WITH CHECK (true);

-- generation_inputs
CREATE POLICY "generation_inputs_select_own" ON generation_inputs
FOR SELECT TO appuser USING (
    EXISTS (
        SELECT 1 FROM sessions
        WHERE sessions.session_id = generation_inputs.session_id
        AND sessions.user_id = auth.uid()
    )
);

CREATE POLICY "generation_inputs_insert_own"
ON generation_inputs
FOR INSERT
TO appuser
WITH CHECK (
    EXISTS (
        SELECT 1 FROM sessions
        WHERE sessions.session_id = generation_inputs.session_id
        AND sessions.user_id = auth.uid()
    )
);

CREATE POLICY "generation_inputs_update_service" ON generation_inputs
FOR UPDATE TO service_role USING (true) WITH CHECK (true);

-- generation_topics
ALTER TABLE generation_topics ENABLE ROW LEVEL SECURITY;

CREATE POLICY "generation_topics_select_own" ON generation_topics
FOR SELECT TO appuser USING (
    EXISTS (
        SELECT 1 FROM generation_inputs
        WHERE generation_inputs.generation_input_id = generation_topics.generation_input_id
        AND EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = generation_inputs.session_id
            AND sessions.user_id = auth.uid()
        )
    )
);

CREATE POLICY "generation_topics_insert_service" ON generation_topics
FOR INSERT TO service_role WITH CHECK (true);

-- generation_images
ALTER TABLE generation_images ENABLE ROW LEVEL SECURITY;

CREATE POLICY "generation_images_select_own" ON generation_images
FOR SELECT TO appuser USING (
    EXISTS (
        SELECT 1 FROM generation_inputs
        WHERE generation_inputs.generation_input_id = generation_images.generation_input_id
        AND EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.session_id = generation_inputs.session_id
            AND sessions.user_id = auth.uid()
        )
    )
);

CREATE POLICY "generation_images_insert_own"
ON generation_images
FOR INSERT
TO appuser
WITH CHECK (
    EXISTS (
        SELECT 1 FROM generation_inputs
        JOIN sessions ON sessions.session_id = generation_inputs.session_id
        WHERE generation_inputs.generation_input_id = generation_images.generation_input_id
        AND sessions.user_id = auth.uid()
    )
);


CREATE POLICY "generation_images_insert_service" ON generation_images
FOR INSERT TO service_role WITH CHECK (true);


-- users
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users_select_own" ON users
FOR SELECT TO appuser USING (auth.uid() = user_id);

CREATE POLICY "users_insert_own" ON users
FOR INSERT TO appuser WITH CHECK (auth.uid() = user_id);

CREATE POLICY "users_update_own" ON users
FOR UPDATE TO appuser
USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);