import logging
from uuid import UUID

import httpx
from arq.connections import RedisSettings
from openai import AsyncOpenAI, BadRequestError
from valkey.asyncio import Valkey

from config import settings
from exceptions import DatabaseError, SessionNotFoundError
from models import GenerationResult, Question, QuestionDTO
from processing import QuestionGenerator
from session_store import SessionStore
from storage import StorageManager
from supabase import AsyncClient, AsyncClientOptions, acreate_client

logger = logging.getLogger(__name__)

REDIS_SETTINGS = RedisSettings(host="valkey", port=6379)


async def startup(ctx):
    ctx["http"] = httpx.AsyncClient(
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
        timeout=httpx.Timeout(30.0),
    )
    ctx["valkey"] = Valkey.from_url(settings.valkey_url)
    service_db = await acreate_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
        options=AsyncClientOptions(httpx_client=ctx["http"]),
    )
    ctx["storage_manager"] = StorageManager(service_db)
    ctx["question_generator"] = QuestionGenerator(AsyncOpenAI())


async def shutdown(ctx):
    await ctx["http"].aclose()
    await ctx["valkey"].aclose()


async def _build_user_client(jwt: str, http: httpx.AsyncClient) -> AsyncClient:
    client = await acreate_client(
        settings.supabase_url,
        settings.supabase_key,
        options=AsyncClientOptions(httpx_client=http),
    )
    client.postgrest.auth(jwt)
    return client


async def generate_questions_task(ctx, session_id: str, job: dict):
    ss_id: UUID = UUID(session_id)
    jwt = job["jwt"]
    user_id = job["user_id"]
    valkey: Valkey = ctx["valkey"]

    lock_key = f"session_lock:{session_id}"
    acquired = await valkey.set(lock_key, "1", nx=True, ex=120)
    if not acquired:
        raise ValueError(f"Generation already in progress for session {session_id}")

    try:
        db = await _build_user_client(jwt, ctx["http"])
        session_store = SessionStore(db)

        await session_store.verify_ownership(ss_id, UUID(user_id))

        question_generator: QuestionGenerator = ctx["question_generator"]
        storage_manager: StorageManager = ctx["storage_manager"]

        try:
            state = await session_store.get(ss_id)
        except SessionNotFoundError:
            logger.error(f"[worker] session {ss_id} not found")
            raise
        except DatabaseError:
            logger.error(f"[worker] database error fetching session {ss_id}")
            raise

        if state.study_set_id is None:
            raise ValueError(f"Session {ss_id} has no study set — upload content first")

        profile = await session_store.get_relevant_profile(state.study_set_id, state)
        raw_images = await storage_manager.list_images(state.study_set_id)
        upload_context = await session_store.get_upload_context(state.study_set_id)

        recent_misconceptions = await session_store.get_recent_misconceptions(session_id=ss_id)

        if upload_context is None and not job.get("raw_markdown"):
            raise ValueError("No upload context found and no markdown provided")

        content = upload_context["content"] if upload_context else job["raw_markdown"]
        generation_input_id = (
            UUID(upload_context["generation_input_id"]) if upload_context else None
        )

        await valkey.set(f"job_status:{session_id}", "in_progress", ex=600)

        result = None
        try:
            async for item in question_generator.generate_questions(
                content,
                raw_images,
                storage_manager,
                state.study_set_id,
                profile,
                recent_misconceptions=recent_misconceptions,
            ):
                logger.info(
                    "[worker] generator yielded type=%s value=%r",
                    type(item).__name__,
                    item,
                )
                if isinstance(item, Question):
                    channel = f"session:{session_id}:questions"
                    payload = QuestionDTO.model_validate(
                        item, from_attributes=True
                    ).model_dump_json()

                    logger.info(
                        "[worker] PUBLISHING question mid_generation=%s channel=%s",
                        item.question_id,
                        channel,
                    )
                    await valkey.publish(channel, payload)
                elif isinstance(item, GenerationResult):
                    result = item
                else:
                    logger.warning(
                        "[worker] UNKNOWN generator output: type=%s value=%r",
                        type(item).__name__,
                        item,
                    )

            if result is None:
                raise ValueError("Generator completed without returning a result")
        except BadRequestError as e:
            logger.error(f"[worker] OpenAI rejected prompt for session {ss_id}: {e.message}")
            raise ValueError("Content was flagged by the AI service — try different material")

        if not result.questions:
            raise ValueError("No questions could be generated from this content")

        # Derive topics from generated questions for resurfacing relevance
        new_topics = {topic for q in result.questions for topic in q.topic_difficulties.keys()}

        resurfaced_questions = await session_store.select_questions_for_resurfacing(
            study_set_id=state.study_set_id,
            new_topics=new_topics,
            state=state,
            target=3,
        )

        # Upsert new questions to pool, get back internal UUIDs in order
        question_uuids = await session_store.upsert_questions_to_study_set(
            study_set_id=state.study_set_id,
            generation_input_id=generation_input_id,
            questions=result.questions,
        )

        resurfaced_ids = {q.id for q in resurfaced_questions if q.id is not None}
        # Resurfaced first so user reviews fading knowledge before new material
        all_uuids = [q.id for q in resurfaced_questions if q.id is not None] + question_uuids

        await session_store.populate_session_questions(
            session_id=ss_id,
            question_uuids=all_uuids,
            resurfaced_ids=resurfaced_ids,
        )

        # Link session to study set, reset position, mark generation complete
        await session_store.finalize_generation(
            session_id=ss_id,
            study_set_id=state.study_set_id,
            generation_input_id=generation_input_id,
            user_id=UUID(user_id),
            status=result.status,
            questions=result.questions,
        )

        await valkey.set(f"job_status:{session_id}", result.status.value, ex=3600)

        all_questions = resurfaced_questions + result.questions
        logger.info(
            f"[worker] generate complete for session {ss_id}: "
            f"{len(result.questions)} new + {len(resurfaced_questions)} resurfaced, "
            f"status={result.status}"
        )

        return {
            "status": result.status.value,
            "questions": [
                QuestionDTO.model_validate(q, from_attributes=True).model_dump()
                for q in all_questions
            ],
            "validation": [v.model_dump() for v in result.validation],
            "message": result.message,
        }

    except Exception:
        await valkey.set(f"job_status:{session_id}", "failed", ex=3600)
        raise

    finally:
        await valkey.delete(lock_key)
        await valkey.delete(f"active_job:{session_id}")


class WorkerSettings:
    functions = [generate_questions_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = REDIS_SETTINGS
