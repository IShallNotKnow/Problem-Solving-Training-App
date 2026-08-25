import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException

from exceptions import DatabaseError, SessionNotFoundError
from models import (
    GenerationStatus,
    Question,
    QuestionResult,
    QuestionScheduling,
    SessionState,
    TopicStats,
    TopicUpdate,
)
from scheduler import (
    fsrs_update,
    initial_difficulty,
    initial_stability,
    next_interval,
    retrievability,
    score_to_fsrs_rating,
)
from supabase import AsyncClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)


class SessionStore:
    def __init__(self, db: AsyncClient):
        self.db = db

    async def get(self, session_id: UUID) -> SessionState:
        logger.debug(f"[session] fetching session {session_id}")
        try:
            row_res, chat_res, history_res = await asyncio.gather(
                self.db.table("sessions")
                .select("*")
                .eq("session_id", str(session_id))
                .single()
                .execute(),
                self.db.table("chat_messages")
                .select("role, content")
                .eq("session_id", str(session_id))
                .order("created_at", desc=True)
                .limit(10)
                .execute(),
                self.db.table("answer_attempts")
                .select("*")
                .eq("session_id", str(session_id))
                .order("answered_at")
                .execute(),
            )
        except Exception as e:
            if "no rows" in str(e).lower() or "pgrst116" in str(e).lower():
                raise SessionNotFoundError(f"Session {session_id} not found") from e
            raise DatabaseError(f"Failed to fetch session {session_id}") from e

        if not row_res.data:
            raise SessionNotFoundError(f"Session {session_id} not found")

        user_id = row_res.data["user_id"]
        study_set_id = row_res.data.get("study_set_id")

        # questions and topic_stats fetched after session row is confirmed
        try:
            if study_set_id:
                questions_res, topic_stats_res = await asyncio.gather(
                    self.db.table("session_questions")
                    .select("position, status, source, questions(*)")
                    .eq("session_id", str(session_id))
                    .order("position")
                    .execute(),
                    self.db.table("topic_stats").select("*").eq("user_id", str(user_id)).execute(),
                )
                questions = []
                for row in questions_res.data:
                    q = Question(**row["questions"])
                    questions.append(q.model_copy(update={"position": row["position"]}))
            else:
                questions = []
                topic_stats_res = await (
                    self.db.table("topic_stats").select("*").eq("user_id", str(user_id)).execute()
                )
        except Exception as e:
            raise DatabaseError(f"Failed to fetch session data for {session_id}") from e

        topic_stats = {
            row["topic"]: TopicStats(
                topic=row["topic"],
                attempts=row["attempts"],
                elo=row["elo"],
                p_known=row["p_known"],
            )
            for row in topic_stats_res.data
        }

        state = SessionState(
            session_id=session_id,
            study_set_id=UUID(study_set_id) if study_set_id else None,
            label=row_res.data["label"],
            current_position=row_res.data["current_position"],
            created_at=row_res.data["created_at"],
            topic_stats=topic_stats,
            questions=questions,
            chat_history=list(reversed(chat_res.data)),
            history=[QuestionResult(**h) for h in history_res.data],
        )
        logger.info(
            f"[session] loaded session {session_id}: {len(state.questions)} questions, "
            f"position={state.current_position}, {len(state.topic_stats)} topics tracked"
        )
        return state

    async def submit_answer_atomic(
        self,
        session_id: UUID,
        question_id: UUID,  # internal UUID, not model-generated text
        user_id: UUID,  # needed for user-scoped topic_stats upsert
        response_str: str,
        question_result: QuestionResult,
        scheduling: QuestionScheduling,
        next_position: int,  # renamed from next_index
        updates: list[TopicUpdate],
        topic_stats: dict[str, TopicStats],
    ) -> None:
        logger.info(
            f"[session] submitting answer atomically for question {question_id}, "
            f"next_position={next_position}, score={question_result.score}"
        )

        rating = score_to_fsrs_rating(question_result.score)

        if scheduling is None or scheduling.times_seen == 0:
            new_stability = initial_stability(rating)
            new_difficulty = initial_difficulty(rating)
            interval = next_interval(new_stability)
        else:
            days_elapsed = (
                datetime.now(timezone.utc) - scheduling.last_attempted_at
            ).total_seconds() / 86400
            new_stability, new_difficulty, interval = fsrs_update(
                scheduling.stability,
                scheduling.difficulty,
                days_elapsed,
                rating,
            )

        due_at = datetime.now(timezone.utc) + timedelta(days=interval)

        await self.db.rpc(
            "submit_answer",
            {
                "p_session_id": str(session_id),
                "p_question_id": str(question_id),
                "p_user_id": str(user_id),
                "p_response": response_str,
                "p_score": question_result.score,
                "p_correct": question_result.correct,
                "p_feedback": question_result.feedback,
                "p_misconception": question_result.misconception,
                "p_next_position": next_position,
                "p_topic_stats": [stats.model_dump() for stats in topic_stats.values()],
                "p_elo_history": [u.model_dump() for u in updates],
                "p_stability": new_stability,
                "p_difficulty": new_difficulty,
                "p_due_at": due_at,
            },
        ).execute()
        logger.info(f"[session] answer submitted successfully for question {question_id}")

    async def verify_ownership(self, session_id: UUID, user_id: UUID) -> None:
        logger.debug(f"[session] verifying ownership of {session_id} for user {user_id}")
        res = await (
            self.db.table("sessions")
            .select("user_id")
            .eq("session_id", str(session_id))
            .maybe_single()
            .execute()
        )
        if not res.data:
            logger.warning(f"[session] session {session_id} not found during ownership check")
            raise HTTPException(status_code=404, detail="Session not found")
        if res.data["user_id"] != str(user_id):
            logger.warning(
                f"[session] ownership mismatch for {session_id}: "
                f"owner={res.data['user_id']}, requester={user_id}"
            )
            raise HTTPException(status_code=403, detail="Forbidden")

    async def verify_study_set_ownership(self, study_set_id: UUID, user_id: UUID) -> None:
        logger.debug(
            f"[session] verifying ownership of study set {study_set_id} for user {user_id}"
        )
        res = await (
            self.db.table("study_sets")
            .select("user_id")
            .eq("study_set_id", str(study_set_id))
            .maybe_single()
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Study set not found")
        if res.data["user_id"] != str(user_id):
            raise HTTPException(status_code=403, detail="Forbidden")

    async def create_study_set(self, user_id: UUID, session_id: UUID, label: str) -> UUID:
        logger.info(f"[session] creating study set for user {user_id}, label='{label}'")
        res = await (
            self.db.table("study_sets")
            .insert({"user_id": str(user_id), "label": label})
            .select("study_set_id")
            .execute()
        )
        study_set_id = UUID(res.data[0]["study_set_id"])
        logger.info(f"[session] study set {study_set_id} created")

        await (
            self.db.table("sessions")
            .update({"study_set_id": str(study_set_id)})
            .eq("session_id", str(session_id))
            .execute()
        )
        logger.info(f"[session] study set {study_set_id} added to session row")
        return study_set_id

    async def create(self, session_id: UUID, label: str, user_id: UUID) -> SessionState:
        logger.info(f"[session] creating session {session_id} for user {user_id}, label='{label}'")
        res = (
            await self.db.table("sessions")
            .insert(
                {
                    "session_id": str(session_id),
                    "label": label,
                    "user_id": str(user_id),
                    # study_set_id intentionally null until generation completes
                }
            )
            .select("*")
            .execute()
        )
        row = res.data[0]
        logger.info(f"[session] session {session_id} created at {row['created_at']}")
        return SessionState(
            session_id=UUID(row["session_id"]),
            label=row["label"],
            created_at=row["created_at"],
        )

    async def save(self, session_id: UUID, state: SessionState) -> None:
        logger.debug(f"[session] saving session {session_id}, position={state.current_position}")
        await (
            self.db.table("sessions")
            .update(
                {
                    "current_position": state.current_position,
                    "last_active_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("session_id", str(session_id))
            .execute()
        )
        # topic_stats now upserted by submit_answer RPC on user_id — save() no longer writes them

    async def get_topic_stats_at_question(
        self, session_id: UUID, question_id: UUID, topics: list[str]
    ) -> dict[str, TopicStats]:
        res = await (
            self.db.table("elo_history")
            .select("topic, new_elo, new_p_known")
            .eq("session_id", str(session_id))
            .eq("question_id", str(question_id))
            .execute()
        )
        return {
            row["topic"]: TopicStats(
                topic=row["topic"],
                elo=row["new_elo"],
                p_known=row["new_p_known"],
                attempts=0,
            )
            for row in res.data
            if row["topic"] in topics
        }

    async def append_chat_turn(
        self, session_id: UUID, user_message: str, assistant_reply: str
    ) -> None:
        logger.debug(f"[session] appending chat turn for session {session_id}")
        await self.db.rpc(
            "append_chat_turn",
            {
                "p_session_id": str(session_id),
                "p_user_content": user_message,
                "p_assistant_content": assistant_reply,
            },
        ).execute()

    async def delete_chat(self, session_id: UUID) -> None:
        await self.db.table("chat_messages").delete().eq("session_id", str(session_id)).execute()

    async def store_upload_context(
        self,
        study_set_id: UUID,
        content: str,
        raw_markdown: str,
        pdf_path: str,
        stored_images: list[dict],
    ) -> UUID:  # returns generation_input_id
        logger.info(
            f"[session] storing upload context for study set {study_set_id}, "
            f"content={len(content)} chars, images={len(stored_images)}"
        )
        res = await (
            self.db.table("generation_inputs")
            .insert(
                {
                    "study_set_id": str(study_set_id),
                    "content": content,
                    "raw_markdown": raw_markdown,
                    "pdf_path": pdf_path,
                    "questions_generated": False,
                }
            )
            .select("generation_input_id")
            .execute()
        )
        generation_input_id = UUID(res.data[0]["generation_input_id"])
        if stored_images:
            await (
                self.db.table("generation_images")
                .insert(
                    [
                        {
                            "generation_input_id": str(generation_input_id),
                            "storage_path": img["storage_path"],
                            "filename": img["filename"],
                            "content_type": img["content_type"],
                            "description": img.get("description"),
                        }
                        for img in stored_images
                    ]
                )
                .execute()
            )
        logger.info(f"[session] upload context stored, generation_input_id={generation_input_id}")
        return generation_input_id

    async def get_upload_context(self, study_set_id: UUID) -> dict | None:
        logger.debug(f"[session] fetching upload context for study set {study_set_id}")
        res = await (
            self.db.table("generation_inputs")
            .select("content, raw_markdown, pdf_path, generation_input_id")
            .eq("study_set_id", str(study_set_id))  # fixed: was session_id
            .order("created_at", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
        if res and res.data:
            logger.info(f"[session] upload context found for study set {study_set_id}")
        else:
            logger.info(f"[session] no upload context found for study set {study_set_id}")
        return res.data if res else None

    async def append_topic_updates(
        self, session_id: UUID, question_id: UUID, updates: list[TopicUpdate]
    ) -> None:
        await (
            self.db.table("elo_history")
            .insert(
                [
                    {
                        "session_id": str(session_id),
                        "question_id": str(question_id),
                        "topic": update.topic,
                        "previous_elo": update.previous_elo,
                        "new_elo": update.new_elo,
                        "elo_delta": update.elo_delta,
                        "previous_p_known": update.previous_p_known,
                        "new_p_known": update.new_p_known,
                        "reason": update.reason,
                    }
                    for update in updates
                ]
            )
            .execute()
        )

    async def get_topic_updates_for_question(
        self, session_id: UUID, question_id: UUID
    ) -> list[TopicUpdate]:
        res = await (
            self.db.table("elo_history")
            .select("*")
            .eq("session_id", str(session_id))
            .eq("question_id", str(question_id))
            .execute()
        )
        return [TopicUpdate(**row) for row in res.data]

    async def get_relevant_profile(self, study_set_id: UUID, state: SessionState) -> dict | None:
        if not state.topic_stats:
            logger.info(
                f"[session] no topic stats yet for study set {study_set_id}, skipping profile"
            )
            return None
        prev_generations = await (
            self.db.table("generation_topics")
            .select("topic, generation_inputs!inner(study_set_id)")
            .eq("generation_inputs.study_set_id", str(study_set_id))  # fixed: was session_id
            .execute()
        )
        all_previous_topics = {row["topic"] for row in prev_generations.data}
        profile = state.topic_profile()
        filtered = {
            bucket: [t for t in topics if t in all_previous_topics]
            for bucket, topics in profile.items()
        }
        if not any(filtered.values()):
            logger.info(
                f"[session] topic profile empty after filtering for study set {study_set_id}"
            )
            return None
        logger.info(f"[session] topic profile for study set {study_set_id}: {filtered}")
        return filtered

    async def get_recent_topic_history(
        self, session_id: UUID, topic: str, limit: int = 5
    ) -> list[float]:
        res = await (
            self.db.table("elo_history")
            .select("new_elo")
            .eq("session_id", str(session_id))
            .eq("topic", topic)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [row["new_elo"] for row in reversed(res.data)]

    async def upsert_questions_to_study_set(
        self,
        study_set_id: UUID,
        generation_input_id: UUID,
        questions: list[Question],
    ) -> list[UUID]:
        """Insert new questions into the study set pool. Returns internal UUIDs in order."""
        if not questions:
            return []
        payload = [
            {
                "study_set_id": str(study_set_id),
                "generation_input_id": str(generation_input_id),
                "question_id": q.question_id,
                "question_type": q.question_type,
                "prompt": q.prompt,
                "correct_answer": q.correct_answer,
                "explanation": q.explanation,
                "topic_difficulties": q.topic_difficulties,
                "choices": q.choices,
                "correct_choice_index": q.correct_choice_index,
                "rubric_points": q.rubric_points,
            }
            for q in questions
        ]
        res = await (
            self.db.table("questions")
            .upsert(
                payload,
                on_conflict="study_set_id,generation_input_id,question_id",
            )
            .select("id, question_id")
            .execute()
        )
        # Return UUIDs in the same order as the input questions
        id_map = {row["question_id"]: UUID(row["id"]) for row in res.data}
        return [id_map[q.question_id] for q in questions]

    async def populate_session_questions(
        self,
        session_id: UUID,
        question_uuids: list[UUID],  # ordered list — position derived from index
        resurfaced_ids: set[UUID] | None = None,
    ) -> None:
        """Populate session_questions for this session from the given question UUIDs."""
        resurfaced_ids = resurfaced_ids or set()
        await (
            self.db.table("session_questions")
            .upsert(
                [
                    {
                        "session_id": str(session_id),
                        "question_id": str(qid),
                        "position": i,
                        "source": "resurfaced" if qid in resurfaced_ids else "generated",
                        "status": "unseen",
                    }
                    for i, qid in enumerate(question_uuids)
                ],
                on_conflict="session_id,question_id",
            )
            .execute()
        )

    async def finalize_generation(
        self,
        session_id: UUID,
        study_set_id: UUID,
        generation_input_id: UUID | None,
        user_id: UUID,
        status: GenerationStatus,
        questions: list[Question],
    ) -> None:
        res = await (
            self.db.table("sessions")
            .select("session_id")
            .eq("session_id", str(session_id))
            .eq("user_id", str(user_id))
            .maybe_single()
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=403, detail="Forbidden")

        logger.info(
            f"[session] finalizing generation for session {session_id}, "
            f"study_set={study_set_id}, status={status}"
        )

        topics_covered = (
            list({t for q in questions for t in q.topic_difficulties})
            if generation_input_id is not None
            else None
        )

        ops = [
            self.db.table("sessions")
            .update(
                {
                    "study_set_id": str(study_set_id),
                    "current_position": 0,
                    "last_active_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("session_id", str(session_id))
            .execute()
        ]

        if generation_input_id is not None:
            input_status = "completed" if status == GenerationStatus.GENERATED else "failed"

            ops.append(
                self.db.table("generation_inputs")
                .update({"questions_generated": True, "status": input_status})
                .eq("generation_input_id", str(generation_input_id))
                .execute()
            )
            if topics_covered:
                ops.append(
                    self.db.table("generation_topics")
                    .insert(
                        [
                            {"generation_input_id": str(generation_input_id), "topic": topic}
                            for topic in topics_covered
                        ]
                    )
                    .execute()
                )

        await asyncio.gather(*ops)
        logger.info(f"[session] generation finalized for session {session_id}")

    async def reset_session(self, session_id: UUID) -> None:
        logger.info(f"[session] resetting session {session_id}")
        try:
            await self.db.rpc(
                "reset_session",
                {"p_session_id": str(session_id)},
            ).execute()
            logger.info(f"[session] session {session_id} reset successfully")
        except Exception as e:
            if "session_not_found" in str(e):
                raise SessionNotFoundError(f"Session {session_id} not found") from e
            raise DatabaseError(f"Failed to reset session {session_id}") from e

    async def get_questions(self, session_id: UUID) -> list[Question]:
        """Used by SSE endpoint to flush existing questions on reconnect."""
        try:
            res = await (
                self.db.table("session_questions")
                .select("position, status, source, questions(*)")
                .eq("session_id", str(session_id))
                .order("position")
                .execute()
            )
            questions = []
            for row in res.data:
                q = Question(**row["questions"])
                questions.append(q.model_copy(update={"position": row["position"]}))
            return questions
        except Exception as e:
            raise DatabaseError(f"Failed to fetch questions for session {session_id}") from e

    async def select_questions_for_resurfacing(
        self,
        study_set_id: UUID,  # resurfacing draws from study set pool, not session
        new_topics: set[str],
        state: SessionState,
        target: int,
    ) -> list[Question]:
        now = datetime.now(timezone.utc)

        # Reads from question_scheduling which is user+question scoped
        res = await self.db.rpc(
            "get_resurfacing_candidates",
            {"p_study_set_id": str(study_set_id)},
        ).execute()

        candidates = []
        for row in res.data:
            if not row.get("last_attempted_at"):
                continue
            days_elapsed = (now - datetime.fromisoformat(row["last_attempted_at"])).days
            p_known = state.topic_stats.get(row["topic"], TopicStats(topic=row["topic"])).p_known
            r = retrievability(p_known, days_elapsed)

            if r >= 0.9:
                continue

            topic_overlap = len(set(row["topics"]) & new_topics)
            candidates.append(
                {
                    "question": Question(**row),
                    "retrievability": r,
                    "topic_overlap": topic_overlap,
                    "p_known": p_known,
                }
            )

        candidates.sort(
            key=lambda c: (
                -c["topic_overlap"],
                c["retrievability"],
                c["p_known"],
            )
        )

        return [c["question"] for c in candidates[:target]]

    async def get_question_scheduling(
        self, user_id: UUID, question_id: UUID
    ) -> QuestionScheduling | None:
        res = await (
            self.db.table("question_scheduling")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("question_id", str(question_id))
            .maybe_single()
            .execute()
        )
        if not res or not res.data:
            return None
        return QuestionScheduling(**res.data)
