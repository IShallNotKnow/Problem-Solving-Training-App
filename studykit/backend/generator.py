import logging
from uuid import UUID

from arq.connections import RedisSettings
from openai import AsyncOpenAI
from supabase import AsyncClient, acreate_client

from config import settings
from exceptions import DatabaseError, SessionNotFoundError
from models import QuestionDTO
from processing import QuestionGenerator
from session_store import SessionStore
from storage import StorageManager

logger = logging.getLogger(__name__)

REDIS_SETTINGS = RedisSettings(host="valkey", port=6379)


async def _build_user_client(jwt: str) -> AsyncClient:
    client = await acreate_client(
        settings.supabase_url,
        settings.supabase_key,
    )
    client.postgrest.auth(jwt)
    return client


async def startup(ctx):
    # service client has no JWT dependency — safe to build once at startup
    service_db = await acreate_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )
    ctx["storage_manager"] = StorageManager(service_db)
    ctx["question_generator"] = QuestionGenerator(AsyncOpenAI())


async def shutdown(ctx):
    pass


async def generate_questions_task(ctx, session_id: UUID, job: dict):
    jwt = job["jwt"]
    user_id = job["user_id"]

    db = await _build_user_client(jwt)
    session_store = SessionStore(db)

    await session_store.verify_ownership(session_id, UUID(user_id))

    question_generator: QuestionGenerator = ctx["question_generator"]
    storage_manager: StorageManager = ctx["storage_manager"]

    try:
        state = await session_store.get(session_id)
    except SessionNotFoundError:
        logger.error(f"[worker] session {session_id} not found")
        raise
    except DatabaseError:
        logger.error(f"[worker] database error fetching session {session_id}")
        raise

    profile = await session_store.get_relevant_profile(session_id, state)
    raw_images = await storage_manager.list_images(session_id)
    upload_context = await session_store.get_upload_context(session_id)

    if upload_context is None and not job.get("raw_markdown"):
        raise ValueError("No upload context found and no markdown provided")

    content = upload_context["content"] if upload_context else job["raw_markdown"]

    result = await question_generator.generate_questions(
        content, raw_images, storage_manager, session_id, profile
    )

    if not result.questions:
        raise ValueError("No questions could be generated from this content")

    await session_store.replace_questions_and_finalize(
        session_id=session_id,
        questions=result.questions,
        generation_input_id=upload_context["generation_input_id"] if upload_context else None,
    )
    logger.info(
        f"[endpoint] generate complete for session {session_id}: {len(result.questions)} questions, status={result.status}"
    )

    return {
        "status": result.status,
        "questions": [
            QuestionDTO.model_validate(q, from_attributes=True).model_dump()
            for q in result.questions
        ],
        "validation": result.validation,
        "message": result.message,
    }


class WorkerSettings:
    functions = [generate_questions_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = REDIS_SETTINGS
