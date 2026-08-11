-- study_sets
CREATE INDEX idx_study_sets_user_id
  ON study_sets (user_id);

-- session_questions
CREATE INDEX idx_session_questions_session_id
  ON session_questions (session_id);
CREATE INDEX idx_session_questions_position
  ON session_questions (session_id, position);
CREATE INDEX idx_session_questions_question_id
  ON session_questions (question_id);

-- question_scheduling
CREATE INDEX idx_question_scheduling_user_id
  ON question_scheduling (user_id);
CREATE INDEX idx_question_scheduling_due_at
  ON question_scheduling (user_id, due_at ASC NULLS FIRST);

-- topic_stats now user-scoped
CREATE INDEX idx_topic_stats_user_id
  ON topic_stats (user_id);

-- questions now scoped to study_set
CREATE INDEX idx_questions_study_set_id
  ON questions (study_set_id);
CREATE INDEX idx_questions_generation_input_id
  ON questions (generation_input_id);