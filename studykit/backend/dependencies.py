from dotenv import load_dotenv
from fastapi import Depends, Request
from openai import AsyncOpenAI

from config import settings
from difficulty_engine import DifficultyController
from processing import (
    AnswerValidator,
    AsyncPDFProcessor,
    ConceptExtractor,
    ImageFilter,
    QuestionGenerator,
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


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def get_service_supabase(request: Request) -> AsyncClient:
    """Service role client — storage operations only. Bypasses RLS."""
    return request.app.state.service


async def get_user_supabase(request: Request) -> AsyncClient:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")

    client = await acreate_client(
        SUPABASE_URL,
        SUPABASE_ANON_KEY,
        options=AsyncClientOptions(httpx_client=request.app.state.http),
    )
    client.postgrest.auth(token)
    return client


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------


def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI()  # reads OPENAI_API_KEY from env


def get_pdf_processor() -> AsyncPDFProcessor:
    return AsyncPDFProcessor()


def get_image_filter(client: AsyncOpenAI = Depends(get_openai_client)) -> ImageFilter:
    return ImageFilter(client)


def get_text_filter() -> TextFilter:
    return TextFilter()


def get_concept_extractor() -> ConceptExtractor:
    return ConceptExtractor()


def get_question_generator(client: AsyncOpenAI = Depends(get_openai_client)) -> QuestionGenerator:
    return QuestionGenerator(client)


def get_answer_validator(client: AsyncOpenAI = Depends(get_openai_client)) -> AnswerValidator:
    return AnswerValidator(client)


def get_difficulty_controller() -> DifficultyController:
    return DifficultyController()


def get_study_chat_assistant(
    client: AsyncOpenAI = Depends(get_openai_client),
) -> StudyChatAssistant:
    return StudyChatAssistant(client)


async def get_session_store(db: AsyncClient = Depends(get_user_supabase)) -> SessionStore:
    return SessionStore(db)


async def get_storage_manager(
    service: AsyncClient = Depends(get_service_supabase),
) -> StorageManager:
    return StorageManager(service)
