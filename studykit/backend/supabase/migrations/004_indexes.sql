-- session lookup by user (list_sessions, verify_ownership)
CREATE INDEX idx_sessions_user_id ON sessions (user_id);
CREATE INDEX idx_sessions_last_active ON sessions (last_active_at DESC);

-- questions ordered by position (get)
CREATE INDEX idx_questions_session_position ON questions (session_id, position);

-- answer history lookup (idempotency check in submit_answer)
CREATE INDEX idx_answer_attempts_session_question ON answer_attempts (session_id, question_id);

-- elo history per question (get_topic_updates_for_question)
CREATE INDEX idx_elo_history_session_question ON elo_history (session_id, question_id);

-- elo history per topic (get_recent_topic_history)
CREATE INDEX idx_elo_history_session_topic_time ON elo_history (session_id, topic, created_at DESC);

-- chat messages time-ordered per session
CREATE INDEX idx_chat_messages_session_time ON chat_messages (session_id, created_at DESC);

-- generation inputs per session (get_upload_context)
CREATE INDEX idx_generation_inputs_session ON generation_inputs (session_id, created_at DESC);

-- generation topics for profile building
CREATE INDEX idx_generation_topics_input ON generation_topics (generation_input_id);