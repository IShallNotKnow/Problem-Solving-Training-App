import asyncio
import logging
import traceback
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import httpx
from arq import create_pool
from arq.jobs import Job, JobStatus, DeserializationError
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import APIStatusError, BadRequestError, RateLimitError
from pydantic import ValidationError
from slowapi import Limiter
from slowapi.util import get_remote_address
from valkey.asyncio import Valkey

from auth import get_current_user
from config import settings
from dependencies import (
    get_answer_validator,
    get_concept_extractor,
    get_difficulty_controller,
    get_image_filter,
    get_pdf_processor,
    get_session_store,
    get_storage_manager,
    get_study_chat_assistant,
    get_text_filter,
    get_user_supabase,
)
from exceptions import DatabaseError, RateLimitExceeded, SessionNotFoundError, StorageError
from generator import REDIS_SETTINGS
from models import (
    AnswerRequest,
    AnswerResponse,
    ChatRequest,
    ChatResponse,
    CreateSessionRequest,
    GenerateRequest,
    GenerationResultDTO,
    QuestionDTO,
    SessionContext,
    SessionStateDTO,
    SessionSummary,
    UploadResponse,
)
from processing import (
    MAX_PDF_SIZE,
    AnswerValidator,
    AsyncPDFProcessor,
    ConceptExtractor,
    DifficultyController,
    ImageFilter,
    StudyChatAssistant,
    TextFilter,
)
from session_store import SessionStore
from storage import StorageManager
from supabase import AsyncClient, AsyncClientOptions, acreate_client

load_dotenv()

SUPABASE_URL: str = settings.supabase_url
SUPABASE_ANON_KEY: str = settings.supabase_key
SUPABASE_SERVICE_ROLE_KEY: str = settings.supabase_service_role_key

MODEL = "gpt-5-mini"

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — initialising HTTP pool and Supabase service client")
    app.state.http = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
        ),
        timeout=httpx.Timeout(30.0),
    )

    app.state.service = await acreate_client(
        SUPABASE_URL,
        SUPABASE_SERVICE_ROLE_KEY,
        options=AsyncClientOptions(httpx_client=app.state.http),
    )
    app.state.valkey = await Valkey.from_url(settings.valkey_url)

    app.state.arq = await create_pool(REDIS_SETTINGS)
    logger.info("Startup complete")
    yield
    logger.info("Shutting down — closing HTTP pool")

    await app.state.arq.close()
    await app.state.http.aclose()
    await app.state.valkey.aclose()


limiter = Limiter(key_func=get_remote_address, storage_uri=settings.valkey_url)

app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://studykit.dev", "https://www.studykit.dev"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(DatabaseError)
async def database_error_handler(request: Request, exc: DatabaseError):
    logger.error(f"DatabaseError on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "30"},
        content={"error": "service_unavailable", "detail": "Database unavailable, please retry"},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    logger.warning(f"ValueError on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_request", "detail": str(exc)},
    )


@app.exception_handler(asyncio.TimeoutError)
async def async_timeout_error_handler(request: Request, exc: asyncio.TimeoutError):
    logger.warning(f"asyncio.TimeoutError on {request.method} {request.url.path}")
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "10"},
        content={"error": "service_unavailable", "detail": "Request timed out, please retry"},
    )


@app.exception_handler(httpx.TimeoutException)
async def httpx_timeout_error_handler(request: Request, exc: httpx.TimeoutException):
    logger.warning(f"httpx.TimeoutException on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "10"},
        content={"error": "service_unavailable", "detail": "Image fetch timed out, please retry"},
    )


@app.exception_handler(httpx.RequestError)
async def httpx_request_error_handler(request: Request, exc: httpx.RequestError):
    logger.warning(f"httpx.RequestError on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=503,
        content={"error": "service_unavailable", "detail": "Image fetch failed, please retry"},
    )


@app.exception_handler(RateLimitError)
async def rate_limit_error_handler(request: Request, exc: RateLimitError):
    logger.warning(f"OpenAI RateLimitError on {request.method} {request.url.path}")
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": "60"},
        content={
            "error": "rate_limited",
            "detail": "AI service rate limit reached, please retry in a moment",
        },
    )


@app.exception_handler(BadRequestError)
async def bad_request_error_handler(request: Request, exc: BadRequestError):
    logger.error(
        f"OpenAI BadRequestError on {request.method} {request.url.path}: {exc.message}, body={exc.body}"
    )
    return JSONResponse(
        status_code=400,
        content={
            "error": "invalid_request",
            "detail": "Invalid content sent to AI service, check image format or size",
        },
    )


@app.exception_handler(APIStatusError)
async def api_status_error_handler(request: Request, exc: APIStatusError):
    logger.error(
        f"OpenAI APIStatusError on {request.method} {request.url.path}: status={exc.status_code}, body={exc.body}"
    )
    return JSONResponse(
        status_code=502,
        content={"error": "upstream_error", "detail": "AI service returned an error, please retry"},
    )


@app.exception_handler(RuntimeError)
async def runtime_handler(request: Request, exc: RuntimeError):
    error_id = uuid4().hex[:8]
    logger.error(
        f"RuntimeError {error_id} on {request.method} {request.url.path}: {exc}\n{traceback.format_exc()}"
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "detail": "AI service failed to return a valid response",
            "error_id": error_id,
        },
    )


@app.exception_handler(ValidationError)
async def pydantic_validation_error_handler(request: Request, exc: ValidationError):
    logger.warning(f"ValidationError on {request.method} {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": exc.errors()},
    )


@app.exception_handler(StorageError)
async def storage_error_handler(request: Request, exc: StorageError):
    error_id = uuid4().hex[:8]
    logger.error(
        f"StorageError {error_id} on {request.method} {request.url.path}: {exc.operation} failed for {exc.path}, cause={exc.cause}",
        extra={
            "error_id": error_id,
            "operation": exc.operation,
            "path": exc.path,
            "cause": str(exc.cause),
        },
    )
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "30"},
        content={
            "error": "storage_unavailable",
            "detail": "File storage unavailable, please retry",
            "error_id": error_id,
        },
    )


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    error_id = uuid4().hex[:8]
    logger.warning(
        "RateLimitExceeded %s: Client exceeded limit on %s",
        error_id,
        request.url.path,
        extra={
            "error_id": error_id,
            "path": request.url.path,
            "client_host": request.client.host if request.client else "unknown",
        },
    )
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={
            "Retry-After": str(exc.retry_after),
            "X-RateLimit-Reset": str(exc.retry_after),
        },
        content={
            "error": "rate_limit_exceeded",
            "detail": str(exc),
            "error_id": error_id,
            "retry_after_seconds": exc.retry_after,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    error_id = uuid4().hex[:8]
    logger.error(
        f"Unhandled exception {error_id} on {request.method} {request.url.path}: {type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "detail": "An unexpected error occurred",
            "error_id": error_id,
        },
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/sessions", response_model=SessionSummary, status_code=201)
@limiter.limit("5/minute")
async def create_session(
    req: CreateSessionRequest,
    user=Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
):
    session_id = uuid4()
    logger.info(f"[endpoint] POST /sessions user={user['sub']} label='{req.label}'")
    try:
        state = await session_store.create(
            session_id=session_id,
            label=req.label or "Untitled Session",
            user_id=UUID(user["sub"]),
        )
    except DatabaseError:
        raise HTTPException(status_code=503, detail="Database unavailable, please retry")

    return SessionSummary(
        session_id=state.session_id,
        label=state.label,
        current_question_index=0,
        created_at=state.created_at,
        questions_count=0,
    )


@app.post("/sessions/{session_id}/upload", response_model=UploadResponse)
@limiter.limit("1/minute")
async def upload(
    request: Request,
    session_id: UUID,
    label: str,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    pdf_processor: AsyncPDFProcessor = Depends(get_pdf_processor),
    image_filter: ImageFilter = Depends(get_image_filter),
    text_filter: TextFilter = Depends(get_text_filter),
    concept_extractor: ConceptExtractor = Depends(get_concept_extractor),
    storage_manager: StorageManager = Depends(get_storage_manager),
    session_store: SessionStore = Depends(get_session_store),
):
    logger.info(
        f"[endpoint] POST /sessions/{session_id}/upload user={user['sub']} filename={file.filename}"
    )
    content_length = file.headers.get("content-length")
    if content_length and int(content_length) > MAX_PDF_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds the maximum allowed size of {MAX_PDF_SIZE // 1024 // 1024} MB.",
        )

    file.file.seek(0, 2)
    real_size = file.file.tell()
    file.file.seek(0)
    if real_size > MAX_PDF_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds the maximum allowed size of {MAX_PDF_SIZE // 1024 // 1024} MB.",
        )

    logger.info(f"[endpoint] PDF size: {real_size} bytes")
    pdf_bytes = await file.read()
    pdf_name = file.filename

    markdown, items, images = await pdf_processor.extract(pdf_bytes)
    filtered_images = await image_filter.heuristic_filter(images)
    filtered_images, descriptions = await image_filter.semantic_filter(filtered_images)
    filtered_items = await text_filter.item_filter(items)
    scored_pages = await concept_extractor.score_pages(filtered_items)
    content = await concept_extractor.prioritize_content(filtered_items, scored_pages)

    if content is None:
        logger.warning(f"[endpoint] no content extracted from PDF for session {session_id}")
        raise HTTPException(
            status_code=422, detail="No meaningful content could be extracted from this document."
        )

    pdf_path, stored_images = await asyncio.gather(
        storage_manager.store_pdf(session_id, pdf_bytes, pdf_name),
        storage_manager.store_images(session_id, filtered_images, descriptions),
    )

    await session_store.store_upload_context(session_id, content, markdown, pdf_path, stored_images)
    logger.info(f"[endpoint] upload complete for session {session_id}")

    return UploadResponse(
        session_id=session_id, content=content, raw_markdown=markdown, pdf_path=pdf_path
    )


@app.post("/sessions/{session_id}/reset", response_model=SessionStateDTO)
@limiter.limit("2/minute")
async def reset_session(
    session_id: UUID,
    user=Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
):
    logger.info(f"[endpoint] POST /sessions/{session_id}/reset user={user['sub']}")
    await session_store.verify_ownership(session_id, UUID(user["sub"]))
    try:
        await session_store.reset_session(session_id)
        state = await session_store.get(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except DatabaseError:
        raise HTTPException(status_code=503, detail="Database unavailable, please retry")

    return SessionStateDTO(
        session_id=state.session_id,
        label=state.label,
        current_question_index=state.current_question_index,
        topic_stats=state.topic_stats,
        questions=[QuestionDTO.model_validate(q, from_attributes=True) for q in state.questions],
        history=state.history,
        chat_history=state.chat_history,
    )


@app.post("/sessions/{session_id}/generate", status_code=202)
@limiter.limit("2/minute")
async def generate(
    request: Request,
    session_id: UUID,
    req: GenerateRequest,
    user=Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
):
    await session_store.verify_ownership(session_id, UUID(user["sub"]))
    jwt = request.headers.get("Authorization", "").removeprefix("Bearer ")

    existing = await app.state.valkey.get(f"active_job:{session_id}")
    if existing:
        return {"job_id": existing.decode(), "status": "pending"}

    job = await app.state.arq.enqueue_job(
        "generate_questions_task",
        str(session_id),
        {"jwt": jwt, "user_id": user["sub"], "raw_markdown": req.raw_markdown, "label": req.label},
    )
    await app.state.valkey.set(f"active_job:{session_id}", job.job_id, ex=3600)
    return {"job_id": job.job_id, "status": "pending"}


@app.get("/sessions/{session_id}/generate/{job_id}", response_model=GenerationResultDTO)
async def generation_status(
    session_id: UUID,
    job_id: str,
    user=Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
):
    await session_store.verify_ownership(session_id, UUID(user["sub"]))

    job = Job(job_id, app.state.arq)
    status = await job.status()

    if status == JobStatus.not_found:
        raise HTTPException(404, "Job not found or expired")

    if status == JobStatus.complete:
        try:
            result_info = await job.result_info()
        except DeserializationError:
            # stale result from before serialization fixes — treat as expired
            logger.warning(f"[endpoint] stale job result for {job_id}, cannot deserialize")
            raise HTTPException(404, "Job result expired — please regenerate")
        if result_info is None:
            raise HTTPException(500, "Job completed but result unavailable")
        if not result_info.success:
            raise HTTPException(500, str(result_info.result))
        return GenerationResultDTO(**result_info.result)

    return JSONResponse(status_code=202, content={"job_id": job_id, "status": status.value})


@app.get("/sessions", response_model=list[SessionSummary])
@limiter.limit("20/minute")
async def list_sessions(
    user=Depends(get_current_user),
    db: AsyncClient = Depends(get_user_supabase),
):
    logger.info(f"[endpoint] GET /sessions user={user['sub']}")
    res = await (
        db.table("sessions")
        .select(
            "session_id, label, current_question_index, created_at, questions_count, last_active_at"
        )
        .order("last_active_at", desc=True)
        .execute()
    )
    logger.info(f"[endpoint] returning {len(res.data)} sessions for user {user['sub']}")
    return res.data


@app.get("/sessions/{session_id}", response_model=SessionStateDTO)
@limiter.limit("20/minute")
async def get_session(
    session_id: UUID,
    user=Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
):
    logger.info(f"[endpoint] GET /sessions/{session_id} user={user['sub']}")
    await session_store.verify_ownership(session_id, UUID(user["sub"]))
    try:
        state = await session_store.get(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except DatabaseError:
        raise HTTPException(status_code=503, detail="Database unavailable, please retry")

    return SessionStateDTO(
        session_id=state.session_id,
        label=state.label,
        current_question_index=state.current_question_index,
        topic_stats=state.topic_stats,
        questions=[QuestionDTO.model_validate(q, from_attributes=True) for q in state.questions],
        history=state.history,
        chat_history=state.chat_history,
    )


@app.delete("/sessions/{session_id}", status_code=204)
@limiter.limit("50/minute")
async def delete_session(
    session_id: UUID,
    user=Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
):
    logger.info(f"[endpoint] DELETE /sessions/{session_id} user={user['sub']}")
    await session_store.verify_ownership(session_id, UUID(user["sub"]))
    try:
        await (
            session_store.db.table("sessions").delete().eq("session_id", str(session_id)).execute()
        )
        logger.info(f"[endpoint] session {session_id} deleted")
    except Exception as e:
        logger.error(f"[endpoint] failed to delete session {session_id}: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable, please retry")


@app.post("/sessions/{session_id}/answer", response_model=AnswerResponse)
@limiter.limit("45/minute")
async def submit_answer(
    request: Request,
    session_id: UUID,
    req: AnswerRequest,
    user=Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
    answer_validator: AnswerValidator = Depends(get_answer_validator),
    difficulty_controller: DifficultyController = Depends(get_difficulty_controller),
):
    logger.info(
        f"[endpoint] POST /sessions/{session_id}/answer user={user['sub']} question={req.question_id} type={'MCQ' if req.choice_index is not None else 'FRQ'}"
    )
    await session_store.verify_ownership(session_id, UUID(user["sub"]))
    try:
        state = await session_store.get(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except DatabaseError:
        raise HTTPException(status_code=503, detail="Database unavailable, please retry")

    question = next((q for q in state.questions if q.question_id == req.question_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail=f"Question {req.question_id} not found")

    if question.question_type == "MCQ":
        if req.choice_index is None:
            raise HTTPException(status_code=400, detail="MCQ answers require a choice_index.")
        num_choices = len(question.choices or [])
        if num_choices > 0 and not (0 <= req.choice_index < num_choices):
            raise HTTPException(
                status_code=400,
                detail=f"choice_index {req.choice_index} is out of range (0-{num_choices - 1}).",
            )
    else:
        if not req.response or not req.response.strip():
            raise HTTPException(status_code=400, detail="FRQ answers require a non-empty response.")

    for qr in state.history:
        if qr.question_id == req.question_id:
            logger.info(f"[endpoint] returning cached answer for question {req.question_id}")
            past_updates = await session_store.get_topic_updates_for_question(
                session_id, req.question_id
            )
            past_stats = await session_store.get_topic_stats_at_question(
                session_id, req.question_id, question.topics
            )
            return AnswerResponse(
                feedback=qr.feedback,
                score=qr.score,
                topic_stats=past_stats,
                topic_updates=past_updates,
                misconception=qr.misconception,
            )

    if state.questions[state.current_question_index].question_id != req.question_id:
        logger.warning(
            f"[endpoint] out-of-order answer: expected {state.questions[state.current_question_index].question_id}, got {req.question_id}"
        )
        raise HTTPException(
            status_code=409,
            detail=f"Question {req.question_id} is not the current question.",
        )

    try:
        if question.question_type == "MCQ":
            result = answer_validator.grade_mcq(
                response={"question_id": req.question_id, "choice_index": req.choice_index},
                question=question,
                state=state,
            )
        else:
            result = await answer_validator.validate_answer(
                response={"question_id": req.question_id, "response": req.response},
                question=question,
                state=state,
            )
            
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            f"[endpoint] grading failed for question {req.question_id}: {type(e).__name__}: {e}"
        )
        raise HTTPException(status_code=500, detail="An internal server error occurred.")

    question_result = result.results[0]

    def _normalize_topic(t: str) -> str:
        return ''.join(c for c in t if c.isprintable()).strip()

    grader_topics = {_normalize_topic(tr.topic) for tr in question_result.topic_results}
    question_topics = {_normalize_topic(t) for t in question.topics}

    if not question_result.topic_results:
        raise HTTPException(status_code=500, detail="Grading did not return topic results")
    if grader_topics != question_topics:
        logger.warning(f"[endpoint] topic mismatch after normalization: grader={grader_topics} question={question_topics}")
        raise HTTPException(status_code=500, detail="Grading returned topic results that don't match question topics")

    logger.info(f"[endpoint] topic_results topics: {[tr.topic for tr in question_result.topic_results]}")
    logger.info(f"[endpoint] question.topics: {question.topics}")

    if not question_result.topic_results:
        raise HTTPException(status_code=500, detail="Grading did not return topic results")
    returned_topics = [tr.topic for tr in question_result.topic_results]
    if len(returned_topics) != len(set(returned_topics)):
        # Duplicates would apply the ELO/BKT update twice for the same topic.
        raise HTTPException(
            status_code=500,
            detail="Grading returned duplicate topic results",
        )
    if set(returned_topics) != set(question.topics):
        raise HTTPException(
            status_code=500,
            detail="Grading returned topic results that don't match question topics",
        )

    response_str = chr(65 + req.choice_index) if question.question_type == "MCQ" else req.response

    state, updates = difficulty_controller.update(state, question_result, question)
    state.advance()
    logger.info(
        f"[endpoint] answer processed for {req.question_id}: score={question_result.score}, advancing to index {state.current_question_index}"
    )

    await session_store.submit_answer_atomic(
        session_id=session_id,
        question_id=question_result.question_id,
        response_str=response_str,
        question_result=question_result,
        next_index=state.current_question_index,
        updates=updates,
        topic_stats=state.topic_stats,
    )

    return AnswerResponse(
        feedback=question_result.feedback,
        score=question_result.score,
        topic_stats={t: state.topic_stats[t] for t in question.topics},
        topic_updates=updates,
        misconception=question_result.misconception,
    )


@app.post("/sessions/{session_id}/chat", response_model=ChatResponse)
@limiter.limit("45/minute")
async def chat(
    request: Request,
    session_id: UUID,
    req: ChatRequest,
    user=Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
    study_chat: StudyChatAssistant = Depends(get_study_chat_assistant),
):
    logger.info(f"[endpoint] POST /sessions/{session_id}/chat user={user['sub']}")
    await session_store.verify_ownership(session_id, UUID(user["sub"]))
    try:
        state = await session_store.get(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except DatabaseError:
        raise HTTPException(status_code=503, detail="Database unavailable, please retry")

    context = SessionContext.from_state(state)
    reply = await study_chat.respond(req.user_message, context)
    await session_store.append_chat_turn(session_id, req.user_message, reply)
    logger.info(f"[endpoint] chat complete for session {session_id}")

    return ChatResponse(reply=reply, current_question_index=state.current_question_index)
