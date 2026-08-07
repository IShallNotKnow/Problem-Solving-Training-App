import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException

from exceptions import DatabaseError, SessionNotFoundError
from models import (
    Question,
    QuestionResult,
    SessionState,
    TopicStats,
    TopicUpdate,
    GenerationStatus,
)
from supabase import AsyncClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session store — uses user-scoped client so RLS fires on every query
# ---------------------------------------------------------------------------

class SessionStore:
    def __init__(self, db: AsyncClient):
        self.db = db

    async def get(self, session_id: UUID) -> SessionState:
        logger.debug(f"[session] fetching session {session_id}")
        try:
            row_res, questions_res, chat_res, history_res, topic_stats_res = await asyncio.gather(
                self.db.table("sessions")
                .select("*")
                .eq("session_id", str(session_id))
                .single()
                .execute(),
                self.db.table("questions")
                .select("*")
                .eq("session_id", str(session_id))
                .order("position")
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
                self.db.table("topic_stats")
                .select("*")
                .eq("session_id", str(session_id))
                .execute(),
            )
        except Exception as e:
            if "no rows" in str(e).lower() or "pgrst116" in str(e).lower():
                raise SessionNotFoundError(f"Session {session_id} not found") from e
            raise DatabaseError(f"Failed to fetch session {session_id}") from e

        if not row_res.data:
            raise SessionNotFoundError(f"Session {session_id} not found")

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
            label=row_res.data["label"],
            current_question_index=row_res.data["current_question_index"],
            created_at=row_res.data["created_at"],
            topic_stats=topic_stats,
            questions=[Question(**q) for q in questions_res.data],
            chat_history=list(reversed(chat_res.data)),
            history=[QuestionResult(**h) for h in history_res.data],
        )
        logger.info(
            f"[session] loaded session {session_id}: {len(state.questions)} questions, index={state.current_question_index}, {len(state.topic_stats)} topics tracked"
        )
        return state

    async def submit_answer_atomic(
        self,
        session_id: UUID,
        question_id: str,
        response_str: str,
        question_result: QuestionResult,
        next_index: int,
        updates: list[TopicUpdate],
        topic_stats: dict[str, TopicStats],
    ) -> None:
        logger.info(
            f"[session] submitting answer atomically for question {question_id}, next_index={next_index}, score={question_result.score}"
        )
        await self.db.rpc(
            "submit_answer",
            {
                "p_session_id": str(session_id),
                "p_question_id": question_id,
                "p_response": response_str,
                "p_score": question_result.score,
                "p_correct": question_result.correct,
                "p_feedback": question_result.feedback,
                "p_misconception": question_result.misconception,
                "p_next_index": next_index,
                "p_topic_stats": [stats.model_dump() for stats in topic_stats.values()],
                "p_elo_history": [u.model_dump() for u in updates],
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
                f"[session] ownership mismatch for {session_id}: owner={res.data['user_id']}, requester={user_id}"
            )
            raise HTTPException(status_code=403, detail="Forbidden")

    async def create(self, session_id: UUID, label: str, user_id: UUID) -> SessionState:
        logger.info(f"[session] creating session {session_id} for user {user_id}, label='{label}'")
        res = (
            await self.db.table("sessions")
            .insert(
                {
                    "session_id": str(session_id),
                    "label": label,
                    "user_id": str(user_id),
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
        logger.debug(f"[session] saving session {session_id}, index={state.current_question_index}")
        updates = [
            self.db.table("sessions")
            .update(
                {
                    "current_question_index": state.current_question_index,
                    "last_active_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("session_id", str(session_id))
            .execute()
        ]
        if state.topic_stats:
            updates.append(
                self.db.table("topic_stats")
                .upsert(
                    [
                        {**stats.model_dump(), "session_id": str(session_id)}
                        for stats in state.topic_stats.values()
                    ],
                    on_conflict="session_id,topic",
                )
                .execute()
            )
        await asyncio.gather(*updates)

    async def get_topic_stats_at_question(
        self, session_id: UUID, question_id: str, topics: list[str]
    ) -> dict[str, TopicStats]:
        res = await (
            self.db.table("elo_history")
            .select("topic, new_elo, new_p_known")
            .eq("session_id", str(session_id))
            .eq("question_id", question_id)
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

    async def replace_questions(self, session_id: UUID, questions: list[Question]) -> None:
        payload = [{**q.model_dump(), "position": i} for i, q in enumerate(questions)]
        await self.db.rpc(
            "replace_questions",
            {
                "p_session_id": str(session_id),
                "p_questions": payload,
            },
        ).execute()

    async def append_answer(self, session_id: UUID, response: str, result: QuestionResult) -> None:
        await (
            self.db.table("answer_attempts")
            .insert(
                {
                    "session_id": str(session_id),
                    "question_id": result.question_id,
                    "response": response,
                    "score": result.score,
                    "correct": result.correct,
                    "feedback": result.feedback,
                    "misconception": result.misconception,
                }
            )
            .execute()
        )

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
        session_id: UUID,
        content: str,
        raw_markdown: str,
        pdf_path: str,
        stored_images: list[dict],
    ) -> None:
        logger.info(
            f"[session] storing upload context for session {session_id}, content={len(content)} chars, images={len(stored_images)}"
        )
        res = (
            await self.db.table("generation_inputs")
            .insert(
                {
                    "session_id": str(session_id),
                    "content": content,
                    "raw_markdown": raw_markdown,
                    "pdf_path": pdf_path,
                    "questions_generated": False,
                }
            )
            .execute()
        )
        generation_input_id = res.data[0]["generation_input_id"]
        if stored_images:
            await (
                self.db.table("generation_images")
                .insert(
                    [
                        {
                            "generation_input_id": generation_input_id,
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

    async def get_upload_context(self, session_id: UUID) -> dict | None:
        logger.debug(f"[session] fetching upload context for session {session_id}")
        res = await (
            self.db.table("generation_inputs")
            .select("content, raw_markdown, pdf_path, generation_input_id")
            .eq("session_id", str(session_id))
            .order("created_at", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
        if res and res.data:
            logger.info(f"[session] upload context found for session {session_id}")
        else:
            logger.info(f"[session] no upload context found for session {session_id}")
        return res.data if res else None

    async def append_generation_input(
        self, generation_input_id: UUID, questions: list[Question]
    ) -> None:
        topics_covered = list({t for q in questions for t in q.topic_difficulties.keys()})
        logger.info(
            f"[session] finalising generation input {generation_input_id}, topics={topics_covered}"
        )
        await asyncio.gather(
            self.db.table("generation_inputs")
            .update({"questions_generated": True})
            .eq("generation_input_id", generation_input_id)
            .execute(),
            self.db.table("generation_topics")
            .insert(
                [
                    {"generation_input_id": generation_input_id, "topic": topic}
                    for topic in topics_covered
                ]
            )
            .execute(),
        )

    async def append_topic_updates(
        self, session_id: UUID, question_id: str, updates: list[TopicUpdate]
    ) -> None:
        await (
            self.db.table("elo_history")
            .insert(
                [
                    {
                        "session_id": str(session_id),
                        "question_id": question_id,
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
        self, session_id: UUID, question_id: str
    ) -> list[TopicUpdate]:
        res = await (
            self.db.table("elo_history")
            .select("*")
            .eq("session_id", str(session_id))
            .eq("question_id", question_id)
            .execute()
        )
        return [TopicUpdate(**row) for row in res.data]

    async def get_relevant_profile(self, session_id: UUID, state: SessionState) -> dict | None:
        if not state.topic_stats:
            logger.info(f"[session] no topic stats yet for session {session_id}, skipping profile")
            return None
        prev_generations = await (
            self.db.table("generation_topics")
            .select("topic, generation_inputs!inner(session_id)")
            .eq("generation_inputs.session_id", str(session_id))
            .execute()
        )
        all_previous_topics = {row["topic"] for row in prev_generations.data}
        profile = state.topic_profile()
        filtered = {
            bucket: [t for t in topics if t in all_previous_topics]
            for bucket, topics in profile.items()
        }
        if not any(filtered.values()):
            logger.info(f"[session] topic profile empty after filtering for session {session_id}")
            return None
        logger.info(f"[session] topic profile for session {session_id}: {filtered}")
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

    async def replace_questions_and_finalize(
        self,
        session_id: UUID,
        questions: list[Question],
        generation_input_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> None:

        logger.info(
            f"[session] replacing questions for session {session_id}, count={len(questions)}, generation_input_id={generation_input_id}"
        )

        topics_covered = (
            list({t for q in questions for t in q.topic_difficulties})
            if generation_input_id is not None
            else None
        )

        await self.db.rpc(
            "replace_questions_and_finalize",
            {
                "p_session_id": str(session_id),
                "p_questions": [{**q.model_dump(), "position": i} for i, q in enumerate(questions)],
                "p_generation_input_id": str(generation_input_id) if generation_input_id else None,
                "p_topics_covered": topics_covered,
                "p_user_id": str(user_id) if user_id else None,
            },
        ).execute()

    async def reset_session(self, session_id: UUID) -> None:
        logger.info(f"[session] resetting session {session_id}")
        try:
            await self.db.rpc(
                "reset_session",
                {
                    "p_session_id": str(session_id),
                },
            ).execute()
            logger.info(f"[session] session {session_id} reset successfully")
        except Exception as e:
            if "session_not_found" in str(e):
                raise SessionNotFoundError(f"Session {session_id} not found") from e
            raise DatabaseError(f"Failed to reset session {session_id}") from e

    async def upsert_questions(self, session_id: UUID, questions: list[Question]) -> None:
        async def _upsert(question: Question) -> None:
            logger.info(
                f"[session] upserting question {question.question_id} for session {session_id}"
            )
            await (
                self.db.table("questions")
                .upsert(
                    {**question.model_dump(), "session_id": str(session_id)},
                    on_conflict="question_id",
                )
                .execute()
            )

        await asyncio.gather(*(_upsert(question) for question in questions))

    async def delete_questions(self, session_id: UUID) -> None:
        logger.info(f"[session] deleting existing questions for session {session_id}")
        await (
            self.db.table("questions")
            .delete()
            .eq("session_id", str(session_id))
            .execute()
        )

    async def finalize_generation(
        self,
        session_id: UUID,
        generation_input_id: UUID | None,
        user_id: UUID,
        status: GenerationStatus,
        questions: list[Question],
    ) -> None:
        logger.info(
            f"[session] finalizing generation for session {session_id}, "
            f"status={status}, generation_input_id={generation_input_id}"
        )

        topics_covered = (
            list({t for q in questions for t in q.topic_difficulties})
            if generation_input_id is not None
            else None
        )

        # Reset index and mark generation complete — questions already in DB
        ops = [
            self.db.table("sessions")
            .update({
                "current_question_index": 0,
                "last_active_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("session_id", str(session_id))
            .execute()
        ]

        if generation_input_id is not None:
            ops.append(
                self.db.table("generation_inputs")
                .update({"questions_generated": True})
                .eq("generation_input_id", str(generation_input_id))
                .execute()
            )
            if topics_covered:
                ops.append(
                    self.db.table("generation_topics")
                    .insert([
                        {
                            "generation_input_id": str(generation_input_id),
                            "topic": topic,
                        }
                        for topic in topics_covered
                    ])
                    .execute()
                )

        await asyncio.gather(*ops)
        logger.info(f"[session] generation finalized for session {session_id}")