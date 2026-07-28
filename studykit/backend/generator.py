import logging
from uuid import UUID

import httpx
from arq.connections import RedisSettings
from openai import AsyncOpenAI

from config import settings
from exceptions import DatabaseError, SessionNotFoundError
from models import QuestionDTO
from processing import QuestionGenerator
from session_store import SessionStore
from storage import StorageManager
from supabase import AsyncClient, AsyncClientOptions, acreate_client

logger = logging.getLogger(__name__)

REDIS_SETTINGS = RedisSettings(host="valkey", port=6379)


async def startup(ctx):
    # service client has no JWT dependency — safe to build once at startup
    ctx["http"] = httpx.AsyncClient(
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
        timeout=httpx.Timeout(30.0),
    )
    service_db = await acreate_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
        options=AsyncClientOptions(httpx_client=ctx["http"]),
    )
    ctx["storage_manager"] = StorageManager(service_db)
    ctx["question_generator"] = QuestionGenerator(AsyncOpenAI())


async def shutdown(ctx):
    await ctx["http"].aclose()


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

    profile = await session_store.get_relevant_profile(ss_id, state)
    raw_images = await storage_manager.list_images(ss_id)
    upload_context = await session_store.get_upload_context(ss_id)

    if upload_context is None and not job.get("raw_markdown"):
        raise ValueError("No upload context found and no markdown provided")

    content = upload_context["content"] if upload_context else job["raw_markdown"]

    result = await question_generator.generate_questions(
        content, raw_images, storage_manager, ss_id, profile
    )

    if not result.questions:
        raise ValueError("No questions could be generated from this content")

    await session_store.replace_questions_and_finalize(
        ss_id=ss_id,
        questions=result.questions,
        generation_input_id=upload_context["generation_input_id"] if upload_context else None,
    )
    logger.info(
        f"[endpoint] generate complete for session {ss_id}: {len(result.questions)} questions, status={result.status}"
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
