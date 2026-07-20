from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request, status
from fastapi.middleware.cors import CORSMiddleware
from anthropic import AsyncAnthropic, RateLimitError, APIStatusError, BadRequestError
from llama_cloud import AsyncLlamaCloud
from dotenv import load_dotenv
import os
from pathlib import Path
import asyncio
from collections import defaultdict
import httpx
import base64
import json
from typing import Literal
from enum import Enum
from pydantic import BaseModel, model_validator, Field, field_validator, ValidationError
from uuid import UUID, uuid4
from supabase import acreate_client, AsyncClient
from contextlib import asynccontextmanager
from urllib.parse import urlparse
import re
from fastapi.responses import JSONResponse
import traceback
import logging
from datetime import datetime
from auth import get_current_user
from models import (
    Question, QuestionResult, QuestionValidationResult, GenerationResult, GenerationStatus, GenerateRequest,
    SessionState, SessionContext, SessionSummary, AnswerResponse, AnswerRequest, AnswerValidationResult,
    TopicStats, TopicResult, TopicEvidence, TopicUpdate, UploadResponse, ChatRequest, ChatResponse,
    IMAGE_FILTERING_TOOL, ANSWER_VALIDATION_TOOL, QUESTION_VALIDATION_TOOL, QUESTION_GENERATION_TOOL
)

load_dotenv()

SUPABASE_URL: str = os.environ.get("SUPABASE_URL")
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY")
_session_locks: defaultdict[UUID, asyncio.Lock] = defaultdict(asyncio.Lock)

MAX_CONTENT_CHARS = 12_000
MAX_PROMPT_IMAGE_TOKENS = 20_000
TOKENS_PER_PIXEL = 1 / 750

def estimate_tokens(bbox: dict) -> int:
    w = min(bbox["w"], 1568)
    h = min(bbox["h"], 1568)
    return int((w * h) * TOKENS_PER_PIXEL)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.supabase = await acreate_client(SUPABASE_URL, SUPABASE_KEY)
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

async def get_supabase(request: Request) -> AsyncClient:
    return request.app.state.supabase


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class SessionNotFoundError(Exception):
    pass

class DatabaseError(Exception):
    pass

class StorageError(Exception):
    def __init__(self, operation: str, path: str, cause: Exception | None = None):
        self.operation = operation
        self.path = path
        self.cause = cause
        super().__init__(f"Storage {operation} failed for {path}")


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(DatabaseError)
async def database_error_handler(request: Request, exc: DatabaseError):
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "30"},
        content={"error": "service_unavailable", "detail": "Database unavailable, please retry"},
    )

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_request", "detail": str(exc)},
    )

@app.exception_handler(asyncio.TimeoutError)
async def async_timeout_error_handler(request: Request, exc: asyncio.TimeoutError):
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "10"},
        content={"error": "service_unavailable", "detail": "Request timed out, please retry"},
    )

@app.exception_handler(httpx.TimeoutError)
async def httpx_timeout_error_handler(request: Request, exc: httpx.TimeoutError):
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "10"},
        content={"error": "service_unavailable", "detail": "Image fetch timed out, please retry"},
    )

@app.exception_handler(httpx.RequestError)
async def httpx_request_error_handler(request: Request, exc: httpx.RequestError):
    return JSONResponse(
        status_code=503,
        content={"error": "service_unavailable", "detail": "Image fetch failed, please retry"},
    )

@app.exception_handler(RateLimitError)
async def rate_limit_error_handler(request: Request, exc: RateLimitError):
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": "60"},
        content={"error": "rate_limited", "detail": "AI service rate limit reached, please retry in a moment"},
    )

@app.exception_handler(BadRequestError)
async def bad_request_error_handler(request: Request, exc: BadRequestError):
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_request", "detail": "Invalid content sent to AI service, check image format or size"},
    )

@app.exception_handler(APIStatusError)
async def api_status_error_handler(request: Request, exc: APIStatusError):
    return JSONResponse(
        status_code=502,
        content={"error": "upstream_error", "detail": "AI service returned an error, please retry"},
    )

@app.exception_handler(RuntimeError)
async def runtime_handler(request: Request, exc: RuntimeError):
    error_id = uuid4().hex[:8]
    logger.error(f"RuntimeError {error_id}: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": "AI service failed to return a valid response", "error_id": error_id},
    )

@app.exception_handler(ValidationError)
async def pydantic_validation_error_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": exc.errors()},
    )

@app.exception_handler(StorageError)
async def storage_error_handler(request: Request, exc: StorageError):
    error_id = uuid4().hex[:8]
    logger.error(
        f"StorageError {error_id}: {exc.operation} failed for {exc.path}",
        extra={"error_id": error_id, "operation": exc.operation, "path": exc.path, "cause": str(exc.cause)},
    )
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "30"},
        content={"error": "storage_unavailable", "detail": "File storage unavailable, please retry", "error_id": error_id},
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    error_id = uuid4().hex[:8]
    logger.error(f"Unhandled exception {error_id}: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": "An unexpected error occurred", "error_id": error_id},
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

class StorageManager:
    def __init__(self, supabase: AsyncClient):
        self.db = supabase
        self.SAFE_FILENAME = re.compile(r'^[\w\-]+\.(png|jpg|jpeg|webp)$')

    async def list_images(self, session_id: UUID) -> list[dict]:
        response = await (
            self.db.table("generation_images")
            .select("*, generation_inputs!inner(session_id)")
            .eq("generation_inputs.session_id", session_id)
            .execute()
        )
        return response.data

    async def store_pdf(self, session_id: UUID, pdf_bytes: bytes, filename: str) -> str:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        path = f"{session_id}/{Path(filename).stem}_{timestamp}.pdf"
        try:
            await self.db.storage.from_("generation-pdfs").upload(
                path=path,
                file=pdf_bytes,
                file_options={"content-type": "application/pdf"},
            )
            return path
        except Exception as e:
            raise StorageError("upload", path, cause=e) from e

    async def download_image(self, session_id: UUID, storage_path: str) -> bytes | None:
        try:
            filename = Path(storage_path).name
            if not filename or not self.SAFE_FILENAME.match(filename):
                return None
            expected_path = f"{session_id}/{filename}"
            if storage_path != expected_path:
                return None
            session = (
                await self.db.table("sessions")
                .select("session_id")
                .eq("session_id", session_id)
                .maybe_single()
                .execute()
            )
            if not session.data:
                return None
            return await self.db.storage.from_("generation-images").download(storage_path)
        except Exception as e:
            print(f"Failed to download image {storage_path}: {e}")
            return None

    async def store_images(self, session_id: UUID, images: list[dict], image_descriptions: dict[str, str]) -> list[dict]:
        ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/jpg", "image/tiff"}

        async with httpx.AsyncClient() as http_client:
            async def fetch_and_store(img: dict) -> dict | None:
                path = None
                try:
                    response = await http_client.get(img["url"])
                    if response.status_code != 200:
                        return None
                    content_type = img.get("content_type", "image/png")
                    if content_type not in ALLOWED_CONTENT_TYPES:
                        content_type = "image/png"
                    path = f"{session_id}/{uuid4().hex}_{img['filename']}"
                    await self.db.storage.from_("generation-images").upload(
                        path=path,
                        file=response.content,
                        file_options={"content-type": content_type},
                    )
                    return {
                        **{k: v for k, v in img.items() if k not in ("url", "content_type")},
                        "storage_path": path,
                        "content_type": content_type,
                        "description": image_descriptions.get(img["filename"]),
                    }
                except StorageError:
                    raise
                except Exception as e:
                    if path:
                        await self.db.storage.from_("generation-images").remove([path])
                    raise

            results = await asyncio.gather(*(fetch_and_store(img) for img in images), return_exceptions=True)
            failed = [r for r in results if isinstance(r, Exception)]
            if failed:
                logger.error(f"Failed to store {len(failed)} images for session {session_id}: {failed}")
            return [r for r in results if isinstance(r, dict)]


# ---------------------------------------------------------------------------
# PDF processing
# ---------------------------------------------------------------------------

class AsyncPDFProcessor:
    def __init__(self):
        api_key = os.getenv("LLAMA_CLOUD_API_KEY")
        if not api_key:
            raise ValueError("LLAMA_CLOUD_API_KEY is not set")
        self.client = AsyncLlamaCloud(api_key=api_key)

    async def extract(self, file_bytes: bytes) -> tuple[str, list[dict], list[dict]]:
        uploaded = None
        try:
            uploaded = await self.client.files.create(
                file=("document.pdf", file_bytes, "application/pdf"),
                purpose="parse",
            )
            job = await self.client.parsing.parse(
                file_id=uploaded.id,
                tier="agentic",
                version="latest",
                expand=["markdown", "items", "images_content_metadata"],
                output_options={"images_to_save": ["layout", "embedded"]},
            )
            markdown = getattr(job, "markdown", "") or ""
            items = []
            for pages in getattr(getattr(job, "items", None), "pages", []):
                page_number = getattr(pages, "page_number", 0)
                for item in getattr(pages, "items", []):
                    item_data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
                    bbox = item_data.get("bbox")
                    items.append({
                        "type": item_data.get("type"),
                        "level": item_data.get("level"),
                        "value": item_data.get("value"),
                        "md": item_data.get("md"),
                        "page": page_number,
                        "bbox": bbox.model_dump() if hasattr(bbox, "model_dump") else bbox,
                        "grounding": item_data.get("grounding"),
                    })
            images = []
            images_meta = getattr(job, "images_content_metadata", None)
            if images_meta is not None:
                for img in getattr(images_meta, "images", []):
                    images.append({
                        "filename": img.filename,
                        "url": img.presigned_url,
                        "page": img.index,
                        "bbox": img.bbox.model_dump(),
                        "content_type": img.content_type,
                        "category": img.category,
                    })
            return markdown, items, images
        except Exception as e:
            if uploaded is not None:
                try:
                    await self.client.files.delete(uploaded.id)
                except Exception:
                    pass
            raise


# ---------------------------------------------------------------------------
# Filtering + extraction
# ---------------------------------------------------------------------------

class ImageFilter:
    def __init__(self, client):
        self.exclude_categories = {"logo", "icon", "banner", "header", "footer"}
        self.MAX_CONCURRENT = 3
        self.client = client
        self.ALLOWED_IMAGE_DOMAINS = {
            "api.llamacloud.com",
            "storage.llamaindex.ai",
        }

    def _is_safe_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            if parsed.scheme != "https":
                return False
            if parsed.netloc not in self.ALLOWED_IMAGE_DOMAINS:
                return False
            if parsed.username or parsed.password:
                return False
            if parsed.port and parsed.port != 443:
                return False
            return True
        except Exception:
            return False

    async def heuristic_filter(self, images: list[dict]) -> list[dict]:
        if not images:
            return []
        filtered = []
        for image in images:
            width = image["bbox"]["w"]
            height = image["bbox"]["h"]
            if image.get("category") in self.exclude_categories or height < 100 or width < 100:
                continue
            aspect_ratio = width / height
            if aspect_ratio > 10 or aspect_ratio < 0.1:
                continue
            if image.get("category") in {"watermark", "signature", "stamp"}:
                continue
            if width * height < 20000:
                continue
            filtered.append(image)
        return filtered

    async def semantic_filter(self, images: list[dict]) -> tuple[list[dict], dict[str, str]]:
        if not images:
            return [], {}

        final_images: list[dict] = []
        descriptions: dict[str, str] = {}
        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        MAX_IMAGE_BYTES = 5 * 1024 * 1024

        MAGIC_BYTES = {
            b"\x89PNG": "image/png",
            b"\xff\xd8\xff": "image/jpeg",
            b"RIFF": "image/webp",
            b"II*\x00": "image/tiff",
            b"MM\x00*": "image/tiff",
        }

        def validate_image_bytes(data: bytes) -> str | None:
            for magic, content_type in MAGIC_BYTES.items():
                if data[:len(magic)] == magic:
                    return content_type
            return None

        async def process_image(image: dict, http_client: httpx.AsyncClient) -> tuple[dict | None, str | None]:
            async with semaphore:
                try:
                    if not self._is_safe_url(image["url"]):
                        return None, None
                    img_response = await http_client.get(image["url"])
                    img_response.raise_for_status()
                    content = img_response.content
                    if len(content) > MAX_IMAGE_BYTES:
                        return None, None
                    content_type = validate_image_bytes(content)
                    if content_type is None:
                        return None, None
                    base64_image = base64.b64encode(content).decode("utf-8")
                    result = await self.client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=500,
                        tools=[IMAGE_FILTERING_TOOL],
                        tool_choice={"type": "tool", "name": "filter_images"},
                        temperature=0.0,
                        messages=[{"role": "user", "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": base64_image}},
                            {"type": "text", "text": (
                                "Analyze this image from a lecture PDF.\n"
                                "Set 'keep' to True if image contains academically meaningful content "
                                "(e.g. diagram, graph, mathematical figure, chart, technical illustration). "
                                "If 'keep' is true, describe the academic content concisely, "
                                "including any text, labels, or mathematical notation visible that may "
                                "not appear in the lecture notes. Otherwise, return null for the description."
                            )},
                        ]}],
                    )
                    tool_use = next((b for b in result.content if b.type == "tool_use"), None)
                    if tool_use is None:
                        raise ValueError("Validator did not return a tool call.")
                    entry = tool_use.input["filtered_images"][0]
                    if entry["keep"]:
                        return image, entry.get("description")
                    return None, None
                except httpx.HTTPError as e:
                    print(f"Failed to fetch {image.get('filename')}: {e}")
                    return None, None
                except Exception as e:
                    print(f"Unexpected error processing {image.get('filename')}: {e}")
                    return None, None

        async with httpx.AsyncClient(timeout=30) as http_client:
            results = await asyncio.gather(*(process_image(img, http_client) for img in images))

        for image, description in results:
            if image is not None:
                final_images.append(image)
                if description:
                    descriptions[image["filename"]] = description

        return final_images, descriptions


class TextFilter:
    KEEP_TYPES = {"paragraph", "heading", "equation", "table", "figure_caption", "list", "text", "code"}

    async def item_filter(self, items: list[dict]) -> list[dict]:
        if not items:
            return []
        return [item for item in items if item["type"] in self.KEEP_TYPES]


class ConceptExtractor:
    CONCEPT_SIGNALS = {
        "heading": 1.0, "figure_caption": 0.8, "list": 0.7,
        "equation": 0.9, "code": 0.9, "table": 0.7,
        "paragraph": 0.3, "text": 0.2,
    }
    ALWAYS_INCLUDE = {"heading", "equation", "theorem", "definition", "code", "table"}

    async def score_pages(self, items: list[dict]) -> dict[int, float]:
        page_scores: dict[int, float] = {}
        for item in items:
            page = item["page"]
            weight = self.CONCEPT_SIGNALS.get(item.get("type", ""), 0)
            page_scores[page] = page_scores.get(page, 0) + weight
        return page_scores

    async def prioritize_content(self, items: list[dict], page_scores: dict[int, float]) -> str | None:
        sorted_pages = sorted(page_scores, key=page_scores.get, reverse=True)
        page_items_map = {page: [i for i in items if i["page"] == page] for page in sorted_pages}
        must_have = [p for p in sorted_pages if any(i.get("type") in self.ALWAYS_INCLUDE for i in page_items_map[p])]
        optional = [p for p in sorted_pages if p not in must_have and page_scores[p] > 3.0]

        result = []
        total = 0
        seen = set()

        for page in must_have + optional:
            if page in seen:
                continue
            seen.add(page)
            page_text = "\n".join(i["md"] for i in page_items_map[page] if i.get("md"))
            if not page_text:
                continue
            if total + len(page_text) > MAX_CONTENT_CHARS:
                remaining = MAX_CONTENT_CHARS - total
                page_text = page_text[:remaining]
                result.append(f"[TRUNCATED] page {page}\n{page_text}")
                break
            label = "[HIGH PRIORITY]" if page_scores[page] > 3.0 else "[CONTAINS KEY CONTENT]"
            result.append(f"{label} page {page}\n{page_text}")
            total += len(page_text)

        return "\n\n".join(result) or None


# ---------------------------------------------------------------------------
# Question generation + validation
# ---------------------------------------------------------------------------

class QuestionValidator:
    def __init__(self, client):
        self.client = client

    async def validate_questions(
        self,
        questions: list[Question],
        content: str,
        raw_images: list[dict] | None,
    ) -> list[QuestionValidationResult]:
        if not questions:
            return []

        descriptions_block = "\n\nImage descriptions:\n" + "\n".join(
            f"- {img['filename']}: {img['description']}"
            for img in raw_images
            if img.get("description")
        )

        message = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            tools=[QUESTION_VALIDATION_TOOL],
            tool_choice={"type": "tool", "name": "validate_questions"},
            messages=[{"role": "user", "content": f"""You are a study question validator. Evaluate the following questions against the source content.

For each question assess:
- Correctness: is `correct_answer` (and `rubric_points` for FRQ) actually correct given the content?
- Relevance: is it directly testable from the content?
- Depth: does it test understanding or problem-solving rather than rote recall?
- Clarity: is it unambiguous and self-contained without needing the original material?
- Difficulty accuracy: for each topic in `topic_difficulties`, does the stated ELO (300-3000) 
  accurately reflect how hard this question is for a student at that topic's level?
- Topic coverage: do the keys in `topic_difficulties` accurately reflect what the question actually tests?
- MCQ only: are `choices` plausible distractors, with exactly one correct option at `correct_choice_index`?
- FRQ only: do `rubric_points` fully capture what a correct answer must contain?

Source content:
{content}{descriptions_block}

Questions (full generated objects, including answers and rubrics):
{json.dumps([q.model_dump() for q in questions], indent=2)}
"""}],
        )

        tool_use = next((b for b in message.content if b.type == "tool_use"), None)
        if tool_use is None:
            raise ValueError("Validator did not return a tool call.")

        return [
            QuestionValidationResult(
                question_id=entry["question_id"],
                approved=entry["approved"],
                feedback=entry["feedback"] or "",
            )
            for entry in tool_use.input["reviews"]
        ]


class QuestionGenerator:
    def __init__(self, client):
        self.client = client
        self.question_validator = QuestionValidator(client)

    async def _build_image_block(self, image_bytes: bytes, content_type: str) -> dict:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": content_type,
                "data": base64.b64encode(image_bytes).decode("utf-8"),
            },
        }

    async def generate_questions(
        self,
        content: str,
        raw_images: list[dict],
        storage_manager: StorageManager,
        session_id: UUID,
        topic_profile: dict | None = None,
    ) -> GenerationResult:
        balance_instruction = ""
        if topic_profile:
            strong = topic_profile.get("strong", [])
            weak = topic_profile.get("weak", [])
            unseen = topic_profile.get("unseen", [])
            parts = []
            if weak:
                parts.append(f"Prioritize questions on weak topics: {', '.join(weak)}. At least 8 of 20 questions should target these.")
            if strong:
                parts.append(f"Include 4-6 questions on strong topics ({', '.join(strong)}) to maintain retention.")
            if unseen:
                parts.append(f"Cover unseen topics at least once each: {', '.join(unseen)}.")
            balance_instruction = "\n\n" + " ".join(parts) if parts else ""

        message_content: list[dict] = [{
            "type": "text",
            "text": (
                "You are a study assistant.\n\n"
                "Based on the following content and images, generate 20 study questions "
                "(10 MCQ, 10 FRQ) that test understanding of the key concepts and "
                f"problem-solving skills.\n\nContent:\n{content}{balance_instruction}\n\nImages:"
            ),
        }]

        image_bytes_list = await asyncio.gather(
            *(storage_manager.download_image(session_id, img["storage_path"]) for img in raw_images),
            return_exceptions=True,
        )

        image_token_budget = 0
        for i, (img, image_bytes) in enumerate(zip(raw_images, image_bytes_list), start=1):
            estimated_tokens = estimate_tokens(img["bbox"]) if img.get("bbox") else 0
            if image_token_budget + estimated_tokens > MAX_PROMPT_IMAGE_TOKENS:
                if img.get("description"):
                    message_content.append({"type": "text", "text": f"Image {i} description (budget exceeded):\n{img['description']}"})
                continue
            if image_bytes is not None:
                message_content.append(await self._build_image_block(image_bytes, img.get("content_type", "image/png")))
                image_token_budget += estimated_tokens
            if img.get("description"):
                message_content.append({"type": "text", "text": f"Image {i} description:\n{img['description']}"})

        MAX_RETRIES = 3
        attempts = 0
        approved_questions: dict[str, Question] = {}
        validation: list[QuestionValidationResult] = []
        feedback_history: dict[str, str] = {}

        while attempts < MAX_RETRIES:
            n_still_needed = 20 - len(approved_questions)
            if n_still_needed == 0:
                break

            current_content = message_content.copy()
            if feedback_history:
                feedback_str = "\n".join(f"- {qid}: {fb}" for qid, fb in feedback_history.items())
                current_content.append({
                    "type": "text",
                    "text": (
                        f"The following {len(feedback_history)} question(s) were rejected. "
                        f"Generate exactly {n_still_needed} replacement question(s) with new unique IDs. "
                        f"Fix these issues:\n{feedback_str}"
                    ),
                })
            else:
                current_content.append({"type": "text", "text": "Generate exactly 20 questions (10 MCQ, 10 FRQ)."})

            message = await self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                tools=[QUESTION_GENERATION_TOOL],
                tool_choice={"type": "tool", "name": "generate_questions"},
                messages=[{"role": "user", "content": current_content}],
            )

            tool_use = next((b for b in message.content if b.type == "tool_use"), None)
            if tool_use is None:
                raise RuntimeError("Model failed to return a tool call despite forced tool_choice")

            new_questions = [Question(**q) for q in tool_use.input["questions"]]
            new_questions = [q for q in new_questions if q.question_id not in approved_questions]

            seen_ids: set[str] = set()
            deduplicated = []
            for q in new_questions:
                if q.question_id not in seen_ids:
                    seen_ids.add(q.question_id)
                    deduplicated.append(q)
                else:
                    logger.warning(f"Duplicate question_id {q.question_id} in batch, skipping")
            new_questions = deduplicated

            new_validation = await self.question_validator.validate_questions(new_questions, content, raw_images)
            rejected_ids = {r.question_id for r in new_validation if not r.approved}
            for q in new_questions:
                if q.question_id not in rejected_ids:
                    approved_questions[q.question_id] = q

            existing = {r.question_id: r for r in validation}
            for r in new_validation:
                existing[r.question_id] = r
            validation = list(existing.values())

            feedback_history = {r.question_id: r.feedback for r in new_validation if not r.approved}
            attempts += 1

        all_approved = len(approved_questions) == 20
        return GenerationResult(
            status=GenerationStatus.GENERATED if all_approved else GenerationStatus.FAILED_VALIDATION,
            questions=list(approved_questions.values()),
            validation=validation,
        )


# ---------------------------------------------------------------------------
# Answer validation + chat
# ---------------------------------------------------------------------------

class AnswerValidator:
    def __init__(self, client):
        self.client = client

    async def validate_answers(
        self,
        responses: list[dict],
        questions: list[Question],
        state: SessionState,
    ) -> AnswerValidationResult:
        valid_ids = {q.question_id for q in questions}
        unknown = [r["question_id"] for r in responses if r["question_id"] not in valid_ids]
        if unknown:
            raise ValueError(f"Responses reference unknown question_ids: {unknown}")

        answer_key = next(
            ({"question_id": q.question_id, "correct_answer": q.correct_answer, "rubric_points": q.rubric_points}
             for q in questions if q.question_id == responses[0]["question_id"]),
            None,
        )
        if answer_key is None:
            raise ValueError(f"Question {responses[0]['question_id']} not found in provided questions")

        payload = {
            "questions": [q.model_dump() for q in questions],
            "answer_key": answer_key,
            "student_responses": responses,
            "topic_stats": {
                t: state.topic_stats[t].model_dump()
                for q in questions
                for t in q.topics
                if t in state.topic_stats
            },
        }

        message = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            tools=[ANSWER_VALIDATION_TOOL],
            tool_choice={"type": "tool", "name": "submit_grading"},
            messages=[{"role": "user", "content": f"""You are grading a student's answer. For each topic evaluate:
- score (0–1): understanding demonstrated.
- confidence (0–1): certainty of evaluation.
- adaptation_signal (-1 to +1): evidence for difficulty adjustment.

Data:
{json.dumps(payload, indent=2)}
"""}],
        )

        tool_use = next(b for b in message.content if b.type == "tool_use")
        results = [QuestionResult(**r) for r in tool_use.input["results"]]
        return AnswerValidationResult(results=results)


class StudyChatAssistant:
    def __init__(self, client):
        self.client = client
        self.MAX_HISTORY_TURNS = 10

    async def respond(self, user_message: str, session_context: SessionContext) -> str:
        question_context = (
            json.dumps(session_context.current_question.model_dump(), indent=2)
            if session_context.current_question
            else "No active question"
        )
        system_prompt = f"""You are a study assistant helping a student work through practice questions.

Current question the student is looking at:
{question_context}

Answer conversationally. If they're asking for a hint, guide them without giving away the full answer."""

        history = session_context.chat_history[-self.MAX_HISTORY_TURNS:]
        messages = [{"role": turn["role"], "content": turn["content"]} for turn in history]
        messages.append({"role": "user", "content": user_message})

        message = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        return next(b.text for b in message.content if b.type == "text")


# ---------------------------------------------------------------------------
# Difficulty controller
# ---------------------------------------------------------------------------

class DifficultyController:
    def __init__(self):
        self.K_BASE = 32.0
        self.MAX_ADAPTATION_INFLUENCE = 50.0

    def clamp(self, value, min_val, max_val):
        return max(min_val, min(max_val, value))

    def compute_evidence(self, tr: TopicResult, stats: TopicStats, question_difficulty: int) -> TopicEvidence:
        adaptation_contribution = tr.adaptation_signal * self.MAX_ADAPTATION_INFLUENCE * tr.confidence
        actual_score = tr.score
        expected_score = 1 / (1 + 10 ** ((question_difficulty - stats.elo) / 400))
        p_obs = tr.confidence * tr.score + (1 - tr.confidence) * 0.5
        K = self.K_BASE * tr.confidence * (0.5 + 0.5 * stats.p_known)
        elo_delta = K * (actual_score - expected_score) + adaptation_contribution
        return TopicEvidence(
            topic=tr.topic,
            expected_score=expected_score,
            actual_score=actual_score,
            elo_delta=elo_delta,
            p_obs=p_obs,
            adaptation_signal=tr.adaptation_signal,
            misconception=tr.misconception,
        )

    def compute_elo_update(self, stats: TopicStats, evidence: TopicEvidence) -> int:
        return int(round(self.clamp(stats.elo + evidence.elo_delta, 300, 3000)))

    def compute_bkt_update(self, stats: TopicStats, evidence: TopicEvidence) -> float:
        P_SLIP, P_GUESS, P_LEARN = 0.1, 0.1, 0.1
        p_known = stats.p_known
        p_correct = p_known * (1 - P_SLIP) + (1 - p_known) * P_GUESS
        p_if_correct = (p_known * (1 - P_SLIP)) / p_correct
        p_if_incorrect = (p_known * P_SLIP) / (p_known * P_SLIP + (1 - p_known) * (1 - P_GUESS))
        p_known_updated = evidence.p_obs * p_if_correct + (1 - evidence.p_obs) * p_if_incorrect
        return p_known_updated + (1 - p_known_updated) * P_LEARN

    def compute_topic_update(self, stats: TopicStats, evidence: TopicEvidence) -> TopicUpdate:
        return TopicUpdate(
            topic=evidence.topic,
            previous_elo=stats.elo,
            new_elo=self.compute_elo_update(stats, evidence),
            elo_delta=evidence.elo_delta,
            previous_p_known=stats.p_known,
            new_p_known=self.compute_bkt_update(stats, evidence),
            reason=f"score={evidence.actual_score:.2f} expected={evidence.expected_score:.2f} confidence={evidence.p_obs:.2f}",
        )

    def update(self, state: SessionState, result: QuestionResult, question: Question) -> tuple[SessionState, list[TopicUpdate]]:
        updates = []
        for tr in result.topic_results:
            if tr.topic not in state.topic_stats:
                state.topic_stats[tr.topic] = TopicStats(topic=tr.topic)
            stats = state.topic_stats[tr.topic]
            evidence = self.compute_evidence(tr, stats, question.topic_difficulties[tr.topic])
            topic_update = self.compute_topic_update(stats, evidence)
            stats.elo = topic_update.new_elo
            stats.p_known = topic_update.new_p_known
            stats.attempts += 1
            updates.append(topic_update)
        state.history.append(result)
        return state, updates


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------

class SessionStore:
    def __init__(self, supabase: AsyncClient):
        self.db = supabase

    async def get(self, session_id: UUID) -> SessionState:
        try:
            row_res, questions_res, chat_res, history_res, topic_stats_res = await asyncio.gather(
                self.db.table("sessions").select("*").eq("session_id", session_id).single().execute(),
                self.db.table("questions").select("*").eq("session_id", session_id).order("position").execute(),
                self.db.table("chat_messages").select("role, content").eq("session_id", session_id).order("created_at", desc=True).limit(10).execute(),
                self.db.table("answer_attempts").select("*").eq("session_id", session_id).order("answered_at", desc=True).limit(10).execute(),
                self.db.table("topic_stats").select("*").eq("session_id", session_id).execute(),
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

        return SessionState(
            session_id=session_id,
            label=row_res.data["label"],
            current_question_index=row_res.data["current_question_index"],
            topic_stats=topic_stats,
            questions=[Question(**q) for q in questions_res.data],
            chat_history=list(reversed(chat_res.data)),
            history=[QuestionResult(**h) for h in history_res.data],
        )

    async def verify_ownership(self, session_id: UUID, user_id: str) -> None:
        """Raises 404 if not found, 403 if owned by someone else."""
        res = await (
            self.db.table("sessions")
            .select("user_id")
            .eq("session_id", session_id)
            .maybe_single()
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Session not found")
        if res.data["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Forbidden")

    async def create(self, session_id: UUID, label: str, user_id: str) -> SessionState:
        await self.db.table("sessions").insert({
            "session_id": session_id,
            "label": label,
            "user_id": user_id,   # ← write ownership at creation
        }).execute()
        return SessionState(session_id=session_id, label=label)

    async def get_or_create(self, session_id: UUID, label: str, user_id: str) -> SessionState:
        try:
            return await self.get(session_id)
        except SessionNotFoundError:
            return await self.create(session_id, label, user_id)

    async def save(self, session_id: UUID, state: SessionState) -> None:
        updates = [
            self.db.table("sessions").update({
                "current_question_index": state.current_question_index,
                "last_active_at": "now()",
            }).eq("session_id", session_id).execute()
        ]
        if state.topic_stats:
            updates.append(
                self.db.table("topic_stats").upsert(
                    [{**stats.model_dump(), "session_id": session_id} for stats in state.topic_stats.values()],
                    on_conflict="session_id,topic",
                ).execute()
            )
        await asyncio.gather(*updates)

    async def replace_questions(self, session_id: UUID, questions: list[Question]) -> None:
        await self.db.table("questions").delete().eq("session_id", session_id).execute()
        if questions:
            await self.db.table("questions").insert([
                {**q.model_dump(), "session_id": session_id, "position": i}
                for i, q in enumerate(questions)
            ]).execute()

    async def append_answer(self, session_id: UUID, response: str, result: QuestionResult) -> None:
        await self.db.table("answer_attempts").insert({
            "session_id": session_id,
            "question_id": result.question_id,
            "response": response,
            "score": result.score,
            "correct": result.correct,
            "feedback": result.feedback,
            "misconception": result.misconception,
        }).execute()

    async def append_chat_turn(self, session_id: UUID, user_message: str, assistant_reply: str) -> None:
        await self.db.rpc("append_chat_turn", {
            "p_session_id": session_id,
            "p_user_content": user_message,
            "p_assistant_content": assistant_reply,
        }).execute()

    async def delete_chat(self, session_id: UUID) -> None:
        await self.db.table("chat_messages").delete().eq("session_id", session_id).execute()

    async def store_upload_context(
        self,
        session_id: UUID,
        content: str,
        raw_markdown: str,
        pdf_path: str,
        stored_images: list[dict],
    ) -> None:
        res = await self.db.table("generation_inputs").insert({
            "session_id": session_id,
            "content": content,
            "raw_markdown": raw_markdown,
            "pdf_path": pdf_path,
            "questions_generated": False,
        }).execute()
        generation_input_id = res.data[0]["generation_input_id"]
        if stored_images:
            await self.db.table("generation_images").insert([
                {
                    "generation_input_id": generation_input_id,
                    "storage_path": img["storage_path"],
                    "filename": img["filename"],
                    "content_type": img["content_type"],
                    "description": img.get("description"),
                }
                for img in stored_images
            ]).execute()

    async def get_upload_context(self, session_id: UUID) -> dict | None:
        res = await (
            self.db.table("generation_inputs")
            .select("content, raw_markdown, pdf_path, generation_input_id")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
        return res.data

    async def append_generation_input(self, generation_input_id: UUID, questions: list[Question]) -> None:
        topics_covered = list({t for q in questions for t in q.topic_difficulties.keys()})
        await asyncio.gather(
            self.db.table("generation_inputs").update({"questions_generated": True}).eq("generation_input_id", generation_input_id).execute(),
            self.db.table("generation_topics").insert([
                {"generation_input_id": generation_input_id, "topic": topic}
                for topic in topics_covered
            ]).execute(),
        )

    async def append_topic_updates(self, session_id: UUID, question_id: str, updates: list[TopicUpdate]) -> None:
        await self.db.table("elo_history").insert([
            {
                "session_id": session_id,
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
        ]).execute()

    async def get_relevant_profile(self, session_id: UUID, state: SessionState) -> dict | None:
        if not state.topic_stats:
            return None
        prev_generations = await (
            self.db.table("generation_topics")
            .select("topic, generation_inputs!inner(session_id)")
            .eq("generation_inputs.session_id", session_id)
            .execute()
        )
        all_previous_topics = {row["topic"] for row in prev_generations.data}
        profile = state.topic_profile()
        filtered = {
            bucket: [t for t in topics if t in all_previous_topics]
            for bucket, topics in profile.items()
        }
        if not any(filtered.values()):
            return None
        return filtered

    async def get_recent_topic_history(self, session_id: UUID, topic: str, limit: int = 5) -> list[float]:
        res = await (
            self.db.table("elo_history")
            .select("new_elo")
            .eq("session_id", session_id)
            .eq("topic", topic)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [row["new_elo"] for row in reversed(res.data)]


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------

def get_anthropic_client() -> AsyncAnthropic:
    return AsyncAnthropic()

def get_pdf_processor() -> AsyncPDFProcessor:
    return AsyncPDFProcessor()

def get_image_filter(client: AsyncAnthropic = Depends(get_anthropic_client)) -> ImageFilter:
    return ImageFilter(client)

def get_text_filter() -> TextFilter:
    return TextFilter()

def get_concept_extractor() -> ConceptExtractor:
    return ConceptExtractor()

def get_question_generator(client: AsyncAnthropic = Depends(get_anthropic_client)) -> QuestionGenerator:
    return QuestionGenerator(client)

def get_answer_validator(client: AsyncAnthropic = Depends(get_anthropic_client)) -> AnswerValidator:
    return AnswerValidator(client)

def get_difficulty_controller() -> DifficultyController:
    return DifficultyController()

def get_study_chat_assistant(client: AsyncAnthropic = Depends(get_anthropic_client)) -> StudyChatAssistant:
    return StudyChatAssistant(client)

async def get_session_store(supabase: AsyncClient = Depends(get_supabase)) -> SessionStore:
    return SessionStore(supabase)

async def get_storage_manager(supabase: AsyncClient = Depends(get_supabase)) -> StorageManager:
    return StorageManager(supabase)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/sessions/{session_id}/upload", response_model=UploadResponse)
async def upload(
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
    pdf_bytes = await file.read()
    pdf_name = file.filename

    markdown, items, images = await pdf_processor.extract(pdf_bytes)
    filtered_images = await image_filter.heuristic_filter(images)
    filtered_images, descriptions = await image_filter.semantic_filter(filtered_images)
    filtered_items = await text_filter.item_filter(items)
    scored_pages = await concept_extractor.score_pages(filtered_items)
    content = await concept_extractor.prioritize_content(filtered_items, scored_pages)

    if content is None:
        raise HTTPException(status_code=422, detail="No meaningful content could be extracted from this document.")

    # user_id flows through to create() if session doesn't exist yet
    await session_store.get_or_create(session_id, label=label, user_id=user["sub"])

    pdf_path, stored_images = await asyncio.gather(
        storage_manager.store_pdf(session_id, pdf_bytes, pdf_name),
        storage_manager.store_images(session_id, filtered_images, descriptions),
    )

    await session_store.store_upload_context(session_id, content, markdown, pdf_path, stored_images)

    return UploadResponse(session_id=session_id, content=content, raw_markdown=markdown, pdf_path=pdf_path)


@app.post("/sessions/{session_id}/reset", response_model=SessionState)
async def reset_session(
    session_id: UUID,
    user=Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
):
    await session_store.verify_ownership(session_id, user["sub"])
    async with _session_locks[session_id]:
        try:
            state = await session_store.get(session_id)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        except DatabaseError:
            raise HTTPException(status_code=503, detail="Database unavailable, please retry")
        state.current_question_index = 0
        await session_store.save(session_id, state)
        return state


@app.post("/sessions/{session_id}/generate", response_model=GenerationResult)
async def generate(
    session_id: UUID,
    req: GenerateRequest,
    user=Depends(get_current_user),
    question_generator: QuestionGenerator = Depends(get_question_generator),
    session_store: SessionStore = Depends(get_session_store),
    storage_manager: StorageManager = Depends(get_storage_manager),
):
    await session_store.verify_ownership(session_id, user["sub"])

    try:
        state = await session_store.get_or_create(session_id, label=req.label, user_id=user["sub"])
    except DatabaseError:
        raise HTTPException(status_code=503, detail="Database unavailable, please retry")

    profile = await session_store.get_relevant_profile(session_id, state)
    raw_images = await storage_manager.list_images(session_id)
    upload_context = await session_store.get_upload_context(session_id)

    if upload_context is None and not req.raw_markdown:
        raise HTTPException(status_code=400, detail="No upload context found for this session")
    content = upload_context["content"] if upload_context else req.raw_markdown

    result = await question_generator.generate_questions(content, raw_images, storage_manager, session_id, profile)

    if result.status != GenerationStatus.GENERATED:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "generation_failed",
                "message": "Question generation failed validation after max retries",
                "approved_count": len(result.questions),
                "validation": [
                    {"question_id": v.question_id, "approved": v.approved, "feedback": v.feedback}
                    for v in result.validation if not v.approved
                ],
            },
        )

    async with _session_locks[session_id]:
        try:
            state = await session_store.get(session_id)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        except DatabaseError:
            raise HTTPException(status_code=503, detail="Database unavailable, please retry")

        state.questions = result.questions
        state.current_question_index = 0
        await asyncio.gather(
            session_store.replace_questions(session_id, result.questions),
            session_store.append_generation_input(
                generation_input_id=upload_context["generation_input_id"],
                questions=result.questions,
            ),
        )
        await session_store.save(session_id, state)

    return result


@app.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(
    user=Depends(get_current_user),
    supabase: AsyncClient = Depends(get_supabase),
):
    res = await (
        supabase.table("sessions")
        .select("session_id, label")
        .eq("user_id", user["sub"])
        .order("last_active_at", desc=True)
        .execute()
    )
    return res.data


@app.get("/sessions/{session_id}", response_model=SessionState)
async def get_session(
    session_id: UUID,
    user=Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
):
    await session_store.verify_ownership(session_id, user["sub"])
    try:
        return await session_store.get(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except DatabaseError:
        raise HTTPException(status_code=503, detail="Database unavailable, please retry")


@app.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: UUID,
    user=Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
):
    await session_store.verify_ownership(session_id, user["sub"])
    try:
        supabase = session_store.db
        await supabase.table("sessions").delete().eq("session_id", session_id).execute()
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable, please retry")


@app.post("/sessions/{session_id}/answer", response_model=AnswerResponse)
async def submit_answer(
    session_id: UUID,
    req: AnswerRequest,
    user=Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
    answer_validator: AnswerValidator = Depends(get_answer_validator),
    difficulty_controller: DifficultyController = Depends(get_difficulty_controller),
):
    await session_store.verify_ownership(session_id, user["sub"])
    async with _session_locks[session_id]:
        try:
            state = await session_store.get(session_id)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        except DatabaseError:
            raise HTTPException(status_code=503, detail="Database unavailable, please retry")

        question = next((q for q in state.questions if q.question_id == req.question_id), None)
        if question is None:
            raise HTTPException(status_code=404, detail=f"Question {req.question_id} not found")

        try:
            result = await answer_validator.validate_answers(
                responses=[{"question_id": req.question_id, "response": req.response}],
                questions=[question],
                state=state,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception:
            raise HTTPException(status_code=500, detail="An internal server error occurred.")

        question_result = result.results[0]
        if not question_result.topic_results:
            raise HTTPException(status_code=500, detail="Grading did not return topic results")
        if {tr.topic for tr in question_result.topic_results} != set(question.topics):
            raise HTTPException(status_code=500, detail="Grading returned topic results that don't match question topics")

        state, updates = difficulty_controller.update(state, question_result, question)
        await asyncio.gather(
            session_store.append_answer(session_id, req.response, question_result),
            session_store.append_topic_updates(session_id, question_result.question_id, updates),
        )
        state.advance()
        await session_store.save(session_id, state)

    return AnswerResponse(
        feedback=question_result.feedback,
        score=question_result.score,
        topic_stats={t: state.topic_stats[t] for t in question.topics},
        topic_updates=updates,
        misconception=question_result.misconception,
    )


@app.post("/sessions/{session_id}/chat", response_model=ChatResponse)
async def chat(
    session_id: UUID,
    req: ChatRequest,
    user=Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
    study_chat: StudyChatAssistant = Depends(get_study_chat_assistant),
):
    await session_store.verify_ownership(session_id, user["sub"])
    try:
        state = await session_store.get(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except DatabaseError:
        raise HTTPException(status_code=503, detail="Database unavailable, please retry")

    context = SessionContext.from_state(state)
    reply = await study_chat.respond(req.user_message, context)
    await session_store.append_chat_turn(session_id, req.user_message, reply)

    return ChatResponse(reply=reply, current_question_index=state.current_question_index)