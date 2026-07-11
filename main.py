from fastapi import FastAPI, HTTPException, Depends, Form, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from anthropic import AsyncAnthropic
from llama_cloud import AsyncLlamaCloud
from dotenv import load_dotenv
import os
from pathlib import Path
import asyncio
import httpx
import base64
import json
from typing import Literal, Annotated
from enum import Enum
from pydantic import BaseModel, HttpUrl, model_validator, Field
from uuid import UUID
from supabase import acreate_client, AsyncClient
from contextlib import asynccontextmanager

load_dotenv()

SUPABASE_URL: str = os.environ.get("SUPABASE_URL")
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY")

MAX_CONTENT_CHARS = 12_000


# ---------------------------------------------------------------------------
# Lifespan — single shared AsyncClient, injected via request.app.state
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.supabase = await acreate_client(SUPABASE_URL, SUPABASE_KEY)
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Dependency — supabase client from app state (no lru_cache needed)
# ---------------------------------------------------------------------------

async def get_supabase(request: Request) -> AsyncClient:
    return request.app.state.supabase


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class GenerationStatus(str, Enum):
    GENERATED = "generated"
    FAILED_VALIDATION = "failed_validation"


class Question(BaseModel):
    question_id: str
    question_type: Literal["MCQ", "FRQ"]
    difficulty: int
    topics: list[str]
    prompt: str
    correct_answer: str
    explanation: str
    choices: list[str] | None = None
    correct_choice_index: int | None = None
    rubric_points: list[str] | None = None

    @model_validator(mode="after")
    def validate_question_type(self) -> "Question":
        if self.question_type == "MCQ":
            if not self.choices or len(self.choices) < 3:
                raise ValueError(f"{self.question_id}: MCQ requires >=3 choices")
            if self.correct_choice_index is None or not (0 <= self.correct_choice_index < len(self.choices)):
                raise ValueError(f"{self.question_id}: invalid correct_choice_index")
        elif self.question_type == "FRQ":
            if not self.rubric_points:
                raise ValueError(f"{self.question_id}: FRQ requires rubric_points")
            if self.choices:
                raise ValueError(f"{self.question_id}: FRQ should not have choices")
        return self
    
class TopicResult(BaseModel):
    topic: str
    score: float
    correct: bool
    feedback: str
    confidence: float
    adaptation_signal: float
    misconception: str | None = None

class TopicUpdate(BaseModel):
    topic: str
    previous_difficulty: float
    new_difficulty: float
    delta: float
    reason: str

class QuestionResult(BaseModel):
    question_id: str
    score: float
    correct: bool
    feedback: str
    topic_results: list[TopicResult] = Field(default_factory=list)


class QuestionValidationResult(BaseModel):
    question_id: str
    approved: bool
    feedback: str = ""


class TopicStats(BaseModel):
    topic: str
    target_level: float = 3.0
    attempts: int = 0
    proficiency: float = 0.0
    confidence: float = 0.0
    recent_history: list[float] = Field(default_factory=list)


class TopicEvidence(BaseModel):
    topic: str
    score: float
    confidence: float
    proficiency_signal: float
    misconception: str | None
    feedback: str


class AnswerValidationResult(BaseModel):
    results: list[QuestionResult]
    avg_score: float = 0.0

    @model_validator(mode="after")
    def compute_avg_score(self) -> "AnswerValidationResult":
        self.avg_score = (
            sum(r.score for r in self.results) / len(self.results)
            if self.results else 0.0
        )
        return self


class GenerationResult(BaseModel):
    status: GenerationStatus
    questions: list[Question] = Field(default_factory=list)
    validation: list[QuestionValidationResult] = Field(default_factory=list)
    message: str = ""


class SessionState(BaseModel):
    session_id: UUID
    label: str
    current_question_index: int = 0
    topic_stats: dict[str, TopicStats] = Field(default_factory=dict)
    questions: list[Question] = Field(default_factory=list)
    history: list[QuestionResult] = Field(default_factory=list)
    chat_history: list[dict] = Field(default_factory=list)

    @property
    def current_question(self) -> Question | None:
        if 0 <= self.current_question_index < len(self.questions):
            return self.questions[self.current_question_index]
        return None

    def advance(self) -> None:
        self.current_question_index += 1

    def get_topic_difficulty(self, topics: list[str]) -> int:
        """Average difficulty across the question's topics, default 3."""
        stats = [self.topic_stats[t] for t in topics if t in self.topic_stats]
        if not stats:
            return 3.0
        return round(sum(s.target_level for s in stats) / len(stats), 1)

    def topic_profile(self, min_attempts: int = 2) -> dict:
        strong, weak, unseen = [], [], []
        for topic, stats in self.topic_stats.items():
            if stats.attempts >= min_attempts:
                if stats.proficiency >= 0.7:
                    strong.append(topic)
                else:
                    weak.append(topic)
            else:
                unseen.append(topic)
        return {"strong": strong, "weak": weak, "unseen": unseen}


class SessionContext(BaseModel):
    current_question: Question | None
    chat_history: list[dict]

    @classmethod
    def from_state(cls, state: SessionState) -> "SessionContext":
        return cls(
            current_question=state.current_question,
            chat_history=state.chat_history[-10:],
        )


class ImageInput(BaseModel):
    filename: str
    url: HttpUrl
    content_type: str = "image/png"


class GenerateRequest(BaseModel):
    label: str
    content: str
    raw_markdown: str = ""
    image_descriptions: dict[str, str] = {}
    pdf_path: str = ""
    topics: list[str]
    topic_profile: dict | None = None


class AnswerRequest(BaseModel):
    question_id: str
    response: str


class ChatRequest(BaseModel):
    user_message: str


class AnswerResponse(BaseModel):
    feedback: str
    score: float
    topic_stats: dict[str, TopicStats]
    misconception: str | None = None


class ChatResponse(BaseModel):
    reply: str
    current_question_index: int


class UploadResponse(BaseModel):
    session_id: UUID
    content: str
    raw_markdown: str
    image_descriptions: dict[str, str]
    pdf_path: str
    topics_added: list[str] 

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

QUESTION_GENERATION_TOOL = {
    "name": "generate_questions",
    "description": "Submit a batch of generated study questions with answers and grading rubrics.",
    "input_schema": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question_id": {
                            "type": "string",
                            "description": "Unique short id, e.g. 'q1', 'q2'."
                        },
                        "question_type": {
                            "type": "string",
                            "enum": ["MCQ", "FRQ"]
                        },
                        "difficulty": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 5,
                            "description": "1 = recall/definition level, 5 = multi-step application requiring synthesis of several concepts."
                        },
                        "topics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "description": "Concept(s) being tested. Single-concept questions have one entry. Synthesis questions (difficulty 4-5) should list all concepts being combined."
                        },
                        "prompt": {
                            "type": "string",
                            "description": "The question text shown to the student."
                        },
                        "choices": {
                            "type": ["array", "null"],
                            "items": {"type": "string"},
                            "minItems": 3,
                            "maxItems": 5,
                            "description": "MCQ only. 3-5 answer options, plain text, no leading letters like 'A)'. Null for FRQ."
                        },
                        "correct_choice_index": {
                            "type": ["integer", "null"],
                            "description": "MCQ only. 0-based index into `choices` for the correct answer. Null for FRQ."
                        },
                        "correct_answer": {
                            "type": "string",
                            "description": "MCQ: the correct choice text. FRQ: a complete, ideal model answer."
                        },
                        "rubric_points": {
                            "type": ["array", "null"],
                            "items": {"type": "string"},
                            "description": "FRQ only. 2-5 discrete, checkable points a correct answer must hit. Null for MCQ."
                        },
                        "explanation": {
                            "type": "string",
                            "description": "1-2 sentences on why the correct answer is right, shown after grading."
                        }
                    },
                    "required": [
                        "question_id", "question_type", "difficulty", "topics",
                        "prompt", "correct_answer", "explanation"
                    ],
                    "additionalProperties": False
                }
            }
        },
        "required": ["questions"],
        "additionalProperties": False
    }
}

QUESTION_VALIDATION_TOOL = {
    "name": "validate_questions",
    "description": "Review a batch of generated questions for correctness, difficulty accuracy, and quality.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question_id": {"type": "string"},
                        "approved": {
                            "type": "boolean",
                            "description": "True only if the question is correct, unambiguous, at its stated difficulty, and tests understanding rather than rote recall."
                        },
                        "feedback": {
                            "type": ["string", "null"],
                            "description": "Required if approved is false. Specific, actionable fix instructions. Null if approved."
                        }
                    },
                    "required": ["question_id", "approved", "feedback"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["reviews"],
        "additionalProperties": False
    }
}

ANSWER_VALIDATION_TOOL = {
    "name": "submit_grading",
    "description": "Submit graded results for each student response.",
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question_id": {"type": "string"},
                        "score": {
                            "type": "number",
                            "description": "0.0 (fully wrong) to 1.0 (fully correct). Use partial credit for FRQs."
                        },
                        "correct": {
                            "type": "boolean",
                            "description": "True only if score >= 0.85"
                        },
                        "feedback": {
                            "type": "string",
                            "description": "1-3 sentences specific to what the student wrote."
                        },
                        "misconception": {
                            "type": ["string", "null"],
                            "description": "Short tag for a recurring error type if present, else null."
                        },
                        "topic_results": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "topic": {"type": "string"},
                                    "correct": {"type": "boolean"},
                                    "confidence": {
                                        "type": "number",
                                        "description": "0.0 to 1.0 — how certain you are in this topic grade given the student's response."
                                    },
                                    "adaptation_signal": {
                                        "type": "number",
                                        "description": (
                                            "Directional evidence for difficulty adjustment, -1.0 to +1.0. "
                                            "This is your read on the student's ability relative to this topic's current difficulty — "
                                            "not a delta computation. The difficulty controller will weigh this against history.\n"
                                            "-1.0: student appears well below current difficulty on this topic.\n"
                                            " 0.0: performance matches expectations.\n"
                                            "+1.0: student appears well above current difficulty on this topic."
                                        ),
                                    },
                                    "misconception": {
                                        "type": ["string", "null"],
                                        "description": "Short tag for a recurring error type specific to this topic if identifiable, else null."
                                    },
                                    "feedback": {"type": "string", "description": "What specifically went wrong or right on this concept."},
                                },
                            },
                            "required": ["topic", "score", "correct", "confidence", "adaptation_signal", "misconception", "feedback"]
                        },
                        "description": "Per-topic breakdown for questions covering multiple concepts. Required when the question has more than one topic."
                    },
                },
                "required": ["question_id", "score", "correct", "feedback", "topic_results"]
            }
        }
    },
    "required": ["results"]
}



# ---------------------------------------------------------------------------
# Storage — PDF + images → Supabase Storage buckets
# ---------------------------------------------------------------------------

class StorageManager:
    def __init__(self, supabase: AsyncClient):
        self.db = supabase
    
    async def list_images(self, session_id: UUID) -> list[dict]:
        response = await (
            self.db.table("generation_images")
            .select("*")
            .eq("session_id", str(session_id))
            .execute()
        )

        return response.data

    async def store_pdf(self, session_id: UUID, pdf_bytes: bytes) -> str:
        path = f"{session_id}/document.pdf"
        await self.db.storage.from_("generation-pdfs").upload(
            path=path,
            file=pdf_bytes,
            file_options={"content-type": "application/pdf"},
        )
        return path

    async def download_image(self, session_id: UUID, storage_path: str) -> bytes | None:
        try:
            session = (
                await self.db.table("sessions")
                .select("id")
                .eq("id", str(session_id))
                .maybe_single()
                .execute()
            )

            if not session.data:
                print(f"Unauthorized access to session {session_id}")
                return None

            if storage_path != f"{session_id}/{storage_path.split('/')[-1]}":
                return None

            return await self.db.storage.from_("generation-images").download(storage_path)
        except Exception as e:
            print(f"Failed to download image {storage_path}: {e}")
            return None

    async def store_images(self, session_id: UUID, images: list[dict], image_descriptions: dict[str, str]) -> list[dict]:
        async with httpx.AsyncClient() as http_client:
            async def fetch_and_store(img: dict) -> dict | None:
                try:
                    response = await http_client.get(img["url"])
                    if response.status_code != 200:
                        return None
                    path = f"{session_id}/{img['filename']}"
                    await self.db.storage.from_("generation-images").upload(
                        path=path,
                        file=response.content,
                        file_options={"content-type": img.get("content_type", "image/png")},
                    )

                    await self.db.table("generation_images").insert({
                        "session_id": str(session_id),
                        "storage_path": path,
                        "filename": img["filename"],
                        "content_type": img.get("content_type", "image/png"),
                        "description": image_descriptions.get(img["filename"]),
                    }).execute()
                    return {
                        **{k: v for k, v in img.items() if k != "url"},
                        "storage_path": path,
                        "description": image_descriptions.get(img["filename"]),
                    }
                except Exception as e:
                    await self.db.storage.from_("generation-images").remove([path])
                    raise

            results = await asyncio.gather(*(fetch_and_store(img) for img in images))
            return [r for r in results if r is not None]


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

        images = [
            {
                "filename": img.filename,
                "url": img.presigned_url,
                "page": img.index,
                "bbox": img.bbox.model_dump(),
                "content_type": img.content_type,
                "category": img.category,
            }
            for img in job.images_content_metadata.images
        ]

        return markdown, items, images


# ---------------------------------------------------------------------------
# Filtering + extraction
# ---------------------------------------------------------------------------

class ImageFilter:
    def __init__(self):
        self.exclude_categories = {"logo", "icon", "banner", "header", "footer"}
        self.client = AsyncAnthropic()

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
            filtered.append(image)

        return filtered

    async def semantic_filter(
        self, images: list[dict], markdown: str
    ) -> tuple[list[dict], dict[str, str]]:
        if not images:
            return [], {}

        final_images: list[dict] = []
        descriptions: dict[str, str] = {}

        async with httpx.AsyncClient() as http_client:
            for image in images:
                try:
                    img_response = await http_client.get(image["url"])
                    if img_response.status_code != 200:
                        continue

                    base64_image = base64.b64encode(img_response.content).decode("utf-8")

                    result = await self.client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=500,
                        temperature=0.0,
                        messages=[{
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": image.get("content_type", "image/png"),
                                        "data": base64_image,
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": (
                                        "Analyze this image from a lecture PDF.\n"
                                        "First line: YES if it contains academically meaningful content "
                                        "(diagram, graph, mathematical figure, chart, technical illustration), "
                                        "NO if decorative or irrelevant.\n\n"
                                        "If YES, second line onward: describe the academic content concisely, "
                                        "including any text, labels, or mathematical notation visible that may "
                                        "not appear in the lecture notes. If NO, stop after the first line."
                                    ),
                                },
                            ],
                        }],
                    )

                    response_text = result.content[0].text.strip()
                    first_line = response_text.split("\n")[0].upper()

                    if first_line == "YES":
                        final_images.append(image)
                        if "\n" in response_text:
                            descriptions[image["filename"]] = response_text.split("\n", 1)[1].strip()

                except Exception as e:
                    print(f"Error filtering image {image.get('filename')}: {e}")
                    final_images.append(image)  # keep on error

        return final_images, descriptions


class TextFilter:
    KEEP_TYPES = {"paragraph", "heading", "equation", "table", "figure_caption", "list", "text", "code"}

    async def item_filter(self, items: list[dict]) -> list[dict]:
        if not items:
            return []
        return [item for item in items if item["type"] in self.KEEP_TYPES]


class ConceptExtractor:
    CONCEPT_SIGNALS = {
        "heading": 1.0,
        "figure_caption": 0.8,
        "list": 0.7,
        "equation": 0.9,
        "code": 0.9,
        "table": 0.7,
        "paragraph": 0.3,
        "text": 0.2,
    }
    ALWAYS_INCLUDE = {"heading", "equation", "theorem", "definition", "code", "table"}

    async def score_pages(self, items: list[dict]) -> dict[int, float]:
        page_scores: dict[int, float] = {}
        for item in items:
            page = item["page"]
            weight = self.CONCEPT_SIGNALS.get(item.get("type", ""), 0)
            page_scores[page] = page_scores.get(page, 0) + weight
        return page_scores

    async def prioritize_content(self, items: list[dict], page_scores: dict[int, float]) -> str:
        sorted_pages = sorted(page_scores, key=page_scores.get, reverse=True)

        result = []
        total = 0
        for page in sorted_pages:            
            page_items = [i for i in items if i["page"] == page]
            score = page_scores[page]
            has_priority_item = any(i.get("type") in self.ALWAYS_INCLUDE for i in page_items)

            if score > 3.0 or has_priority_item:
                page_text = "\n".join(i["md"] for i in page_items if i.get("md"))
                label = "[HIGH PRIORITY]" if score > 3.0 else "[CONTAINS KEY CONTENT]"
                if total + len(page_text) > MAX_CONTENT_CHARS:
                    break
                result.append(f"{label} page {page}\n{page_text}")
                total += len(page_text)
            
        return "\n\n".join(result)


# ---------------------------------------------------------------------------
# Question generation + validation
# ---------------------------------------------------------------------------

class QuestionValidator:
    def __init__(self):
        self.client = AsyncAnthropic()

    async def validate_questions(
        self,
        questions: list[Question],
        content: str,
        image_descriptions: dict[str, str] | None = None,
    ) -> list[QuestionValidationResult]:
        if not questions:
            return []

        descriptions_block = ""
        if image_descriptions:
            descriptions_block = "\n\nImage descriptions:\n" + "\n".join(
                f"- {filename}: {desc}" for filename, desc in image_descriptions.items()
            )

        message = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            tools=[QUESTION_VALIDATION_TOOL],
            tool_choice={"type": "tool", "name": "validate_questions"},
            messages=[{
                "role": "user",
                "content": f"""You are a study question validator. Evaluate the following questions against the source content.

For each question assess:
- Correctness: is `correct_answer` (and `rubric_points` for FRQ) actually correct given the content?
- Relevance: is it directly testable from the content?
- Depth: does it test understanding or problem-solving rather than rote recall?
- Clarity: is it unambiguous and self-contained without needing the original material?
- Difficulty accuracy: does the actual difficulty match its stated `difficulty` (1-5)?
- MCQ only: are `choices` plausible distractors, with exactly one correct option at `correct_choice_index`?
- FRQ only: do `rubric_points` fully capture what a correct answer must contain?

Source content:
{content}{descriptions_block}

Questions (full generated objects, including answers and rubrics):
{json.dumps([q.model_dump() for q in questions], indent=2)}
""",
            }],
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
    def __init__(self, client, validator):
        self.client = client
        self.question_validator = validator

    async def _build_image_block(self, image_bytes: bytes, content_type: str) -> dict:
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": content_type,
                "data": base64_image,
            },
        }

    async def generate_questions(
        self,
        content: str,
        raw_images: list[dict],
        image_descriptions: dict[str, str],
        storage_manager: StorageManager,
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
                parts.append(f"Include 4-6 questions on strong topics ({', '.join(strong)})" 
                             f"to maintain retention — mix these with weak topics in synthesis questions where it makes sense.")
            if unseen:
                parts.append(f"Cover unseen topics at least once each: {', '.join(unseen)}.")
            
            balance_instruction = "\n\n" + " ".join(parts) if parts else ""


        message_content: list[dict] = [{
            "type": "text",
            "text": (
                "You are a study assistant.\n\n"
                "Based on the following content and images, generate 20 study questions "
                "(10 MCQ, 10 FRQ) that test understanding of the key concepts and "
                "problem-solving skills.\n\n"
                f"Content:\n{content}{balance_instruction}\n\nImages:"
            ),
        }]

        image_bytes_list = await asyncio.gather(
            *(storage_manager.download_image(img["storage_path"]) for img in raw_images)
        )
        for i, (img, image_bytes) in enumerate(zip(raw_images, image_bytes_list), start=1):
            if image_bytes is not None:
                message_content.append(await self._build_image_block(image_bytes, img.get("content_type", "image/png")))
            description = image_descriptions.get(img["filename"])
            if description:
                message_content.append({"type": "text", "text": f"Image {i} description:\n{description}"})

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
                feedback_str = "\n".join(
                    f"- {qid}: {fb}" for qid, fb in feedback_history.items()
                )
                current_content.append({
                    "type": "text",
                    "text": (
                        f"The following {len(feedback_history)} question(s) were rejected. "
                        f"Generate exactly {n_still_needed} replacement question(s) with new unique IDs "
                        f"(do not reuse rejected IDs). Fix these issues:\n{feedback_str}"
                    ),
                })
            else:
                current_content.append({
                    "type": "text",
                    "text": "Generate exactly 20 questions (10 MCQ, 10 FRQ).",
                })

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

            seen_ids = [q.question_id for q in new_questions]
            if len(seen_ids) != len(set(seen_ids)):
                raise ValueError("Duplicate question_id in generated batch")

            # validate only the new batch
            new_validation = await self.question_validator.validate_questions(
                new_questions, content, image_descriptions
            )

            # split into approved and rejected
            rejected_ids = {r.question_id for r in new_validation if not r.approved}
            for q in new_questions:
                if q.question_id not in rejected_ids:
                    approved_questions[q.question_id] = q

            # update validation list — replace entries for re-attempted IDs
            existing = {r.question_id: r for r in validation}
            for r in new_validation:
                existing[r.question_id] = r
            validation = list(existing.values())

            # build feedback for next round — only rejected ones from this round
            feedback_history = {
                r.question_id: r.feedback
                for r in new_validation
                if not r.approved
            }

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
            {"question_id": q.question_id, "correct_answer": q.correct_answer, "rubric_points": q.rubric_points}
            for q in questions if q.question_id == responses[0]["question_id"]
        )

        payload = {
            "questions": [q.model_dump() for q in questions],
            "answer_key": answer_key,
            "student_responses": responses,
            "topic_stats": {
                t: state.topic_stats[t].model_dump()
                for q in questions
                for t in q.topics
                if t in state.topic_stats
            }
        }

        message = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            tools=[ANSWER_VALIDATION_TOOL],
            tool_choice={"type": "tool", "name": "submit_grading"},
            messages=[{
                "role": "user",
                "content": f"""You are grading a student's answer. For each topic on this question you evaluate the response based on:
- score (0–1): How well the student demonstrated understanding of this topic.
- confidence (0–1): How confident you are in your evaluation based on the response.
- adaptation_signal (-1 to +1): Based only on this response, how much evidence is there that the student's future questions should become easier or harder?

-1.0
Student failed fundamental concepts that should be secure.

-0.5
Student struggled with expected material.

0.0
Response matches expectations.

+0.5
Student demonstrated strong understanding.

+1.0
Student demonstrated mastery beyond what this question required.

Data:
{json.dumps(payload, indent=2)}
""",
            }],
        )

        tool_use = next(b for b in message.content if b.type == "tool_use")
        results = [QuestionResult(**r) for r in tool_use.input["results"]]
        return AnswerValidationResult(results=results)


class StudyChatAssistant:
    def __init__(self, client):
        self.client = client

    async def respond(self, user_message: str, session_context: SessionContext) -> str:
        question_context = (
            json.dumps(session_context.current_question.model_dump(), indent=2)
            if session_context.current_question
            else "No active question"
        )
        message = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": f"""You are a study assistant helping a student work through practice questions.

Current question the student is looking at:
{question_context}

Recent conversation:
{json.dumps(session_context.chat_history, indent=2)}

Student's message: {user_message}

Answer conversationally. If they're asking for a hint, guide them without giving
away the full answer. If they're asking a concept question, explain clearly.""",
            }],
        )
        return next(b.text for b in message.content if b.type == "text")


# ---------------------------------------------------------------------------
# Difficulty controller
# ---------------------------------------------------------------------------

class DifficultyController:
    def __init__(self):
        ...

    def update(
        self,
        state: SessionState,
        result: QuestionResult,
        topics: list[str],
    ) -> SessionState:
        topic_map: dict[str, bool] = (
            {topic_result.topic: topic_result for topic_result in result.topic_results}
            if result.topic_results else {}
        )

        for topic in topics:
            if topic not in state.topic_stats:
                state.topic_stats[topic] = TopicStats(topic=topic)
            stats = state.topic_stats[topic]
            stats.attempts += 1
            topic_result = topic_map.get(topic)

            if topic_result:
                correct = topic_result.correct
                delta = self.compute_delta(
                    stats,
                    topic_result
                )
            else:
                correct = result.correct
                delta = 0

            if correct:
                stats.correct += 1

            stats.difficulty = max(1, min(5, stats.difficulty + delta))

        state.history.append(result)
        return state

    def compute_delta(self):
        ...


# ---------------------------------------------------------------------------
# Session store — all DB operations, fully async
# ---------------------------------------------------------------------------

class SessionStore:
    def __init__(self, supabase: AsyncClient):
        self.db = supabase

    async def get(self, session_id: UUID) -> SessionState:
        # all four queries run concurrently
        row_res, questions_res, chat_res, history_res = await asyncio.gather(
            self.db.table("sessions").select("*").eq("session_id", session_id).single().execute(),
            self.db.table("questions").select("*").eq("session_id", session_id).order("position").execute(),
            self.db.table("chat_messages").select("role, content").eq("session_id", session_id).order("created_at", desc=True).limit(10).execute(),
            self.db.table("answer_attempts").select("*").eq("session_id", session_id).execute(),
        )
        raw_stats = row_res.data.get("topic_stats", {})
        topic_stats = {t: TopicStats(**s) for t, s in raw_stats.items()}
        label=row_res.data["label"],
        current_question_index=row_res.data["current_question_index"],

        return SessionState(
            session_id=session_id,
            label=label,
            current_question_index=current_question_index,
            topic_stats=topic_stats,
            questions=[Question(**q) for q in questions_res.data],
            chat_history=list(reversed(chat_res.data)),
            history=[QuestionResult(**h) for h in history_res.data],
        )

    async def get_or_create(self, session_id: UUID, label: str) -> SessionState:
        try:
            return await self.get(session_id)
        except Exception:
            await self.db.table("sessions").insert({
                "session_id": session_id,
                "label": label,
                "topic_stats": {},
            }).execute()
            return SessionState(session_id=session_id, label=label)

    async def save(self, session_id: UUID, state: SessionState) -> None:
        await self.db.table("sessions").update({
            "current_question_index": state.current_question_index,
            "topic_stats": {
                t: s.model_dump() for t, s in state.topic_stats.items()
            },
            "last_active_at": "now()",
        }).eq("session_id", session_id).execute()

    async def append_answer(
        self,
        session_id: UUID,
        response: str,          # raw student answer from AnswerRequest
        result: QuestionResult,
    ) -> None:
        await self.db.table("answer_attempts").insert({
            "session_id": session_id,
            "question_id": result.question_id,
            "response": response,
            "score": result.score,
            "correct": result.correct,
            "feedback": result.feedback,
            "misconception": result.misconception,
        }).execute()

    async def append_chat(self, session_id: UUID, role: str, content: str) -> None:
        await self.db.table("chat_messages").insert({
            "session_id": session_id,
            "role": role,
            "content": content,
        }).execute()

    async def delete_chat(self, session_id: UUID) -> None:
        await self.db.table("chat_messages").delete().eq("session_id", session_id).execute()

    async def append_generation_input(
        self,
        session_id: UUID,
        content: str,
        raw_markdown: str,
        image_descriptions: dict[str, str],
        raw_images: list[dict],         # already stored; contain storage_path, no url
        pdf_path: str,
    ) -> None:
        await self.db.table("generation_inputs").insert({
            "session_id": session_id,
            "content": content,
            "raw_markdown": raw_markdown,
            "image_descriptions": image_descriptions,
            "images": raw_images,
            "pdf_path": pdf_path,
        }).execute()


# ---------------------------------------------------------------------------
# Dependency factories — supabase-dependent ones are NOT lru_cached because
# they receive the AsyncClient which is created once in lifespan
# ---------------------------------------------------------------------------

def get_pdf_processor() -> AsyncPDFProcessor:
    return AsyncPDFProcessor()

def get_image_filter() -> ImageFilter:
    return ImageFilter()

def get_text_filter() -> TextFilter:
    return TextFilter()

def get_concept_extractor() -> ConceptExtractor:
    return ConceptExtractor()

def get_question_generator() -> QuestionGenerator:
    return QuestionGenerator()

def get_answer_validator() -> AnswerValidator:
    return AnswerValidator()

def get_difficulty_controller() -> DifficultyController:
    return DifficultyController()

def get_study_chat_assistant() -> StudyChatAssistant:
    return StudyChatAssistant()

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
    pdf_processor: AsyncPDFProcessor = Depends(get_pdf_processor),
    image_filter: ImageFilter = Depends(get_image_filter),
    text_filter: TextFilter = Depends(get_text_filter),
    concept_extractor: ConceptExtractor = Depends(get_concept_extractor),
    storage_manager: StorageManager = Depends(get_storage_manager),
    session_store: SessionStore = Depends(get_session_store),
):  
    pdf_bytes = await file.read()

    # extract
    markdown, items, images = await pdf_processor.extract(pdf_bytes)

    # filter
    filtered_images = await image_filter.heuristic_filter(images)
    filtered_images, descriptions = await image_filter.semantic_filter(filtered_images, markdown)
    filtered_items = await text_filter.item_filter(items)

    # prioritize
    scored_pages = await concept_extractor.score_pages(filtered_items)
    content = await concept_extractor.prioritize_content(filtered_items, scored_pages)

    # store PDF and images concurrently — presigned URLs are ephemeral so do
    # this before returning; storage_path replaces url in raw_images
    pdf_path, stored_images = await asyncio.gather(
        storage_manager.store_pdf(session_id, pdf_bytes),
        storage_manager.store_images(session_id, filtered_images, descriptions),
    )

    # create session row so generate endpoint can reference it
    await session_store.get_or_create(session_id, label=label)

    return UploadResponse(
        session_id=session_id,
        content=content,
        raw_markdown=markdown,
        image_descriptions=descriptions,
        pdf_path=pdf_path,
    )


@app.post("/sessions/{session_id}/generate", response_model=GenerationResult)
async def generate(
    session_id: UUID,
    req: GenerateRequest,
    question_generator: QuestionGenerator = Depends(get_question_generator),
    session_store: SessionStore = Depends(get_session_store),
    storage_manager: StorageManager = Depends(get_storage_manager),
):
    state = await session_store.get_or_create(session_id, label=req.label)
    profile = state.topic_profile() if state.topic_stats else req.topic_profile
    raw_images = await storage_manager.list_images(session_id)

    result = await question_generator.generate_questions(
        req.content, raw_images, req.image_descriptions, storage_manager, profile
    )

    if result.status == GenerationStatus.GENERATED:
        state = await session_store.get_or_create(session_id, label=req.label)
        state.questions = result.questions
        await session_store.save(session_id, state)

        # only store inputs that produced validated questions — keeps training
        # data clean; failed generations are a separate signal if needed later
        await session_store.append_generation_input(
            session_id=session_id,
            content=req.content,
            raw_markdown=req.raw_markdown,
            image_descriptions=req.image_descriptions,
            pdf_path=req.pdf_path,
        )

        return result

    raise HTTPException(status_code=422, detail="Question generation failed validation after max retries")


@app.get("/sessions/{session_id}", response_model=SessionState)
async def get_session(
    session_id: UUID,
    session_store: SessionStore = Depends(get_session_store),
):
    try:
        return await session_store.get(session_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/answer", response_model=AnswerResponse)
async def submit_answer(
    session_id: UUID,
    req: AnswerRequest,
    session_store: SessionStore = Depends(get_session_store),
    answer_validator: AnswerValidator = Depends(get_answer_validator),
    difficulty_controller: DifficultyController = Depends(get_difficulty_controller),
):
    try:
        state = await session_store.get(session_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # get topics from the question being answered
    question = next(
        (q for q in state.questions if q.question_id == req.question_id), None
    )
    if question is None:
        raise HTTPException(status_code=404, detail=f"Question {req.question_id} not found")

    result = await answer_validator.validate_answers(
        responses=[{"question_id": req.question_id, "response": req.response}],
        questions=[question],
        state=state,
    )
    question_result = result.results[0]
    state = difficulty_controller.update(state, question_result, question.topics)
    state.advance()

    await asyncio.gather(
        session_store.save(session_id, state),
        session_store.append_answer(session_id, req.response, question_result),
    )

    return AnswerResponse(
        feedback=question_result.feedback,
        score=question_result.score,
        topic_stats={t: state.topic_stats[t] for t in question.topics},
        misconception=question_result.misconception,
    )


@app.post("/sessions/{session_id}/chat", response_model=ChatResponse)
async def chat(
    session_id: UUID,
    req: ChatRequest,
    session_store: SessionStore = Depends(get_session_store),
    study_chat: StudyChatAssistant = Depends(get_study_chat_assistant),
):
    try:
        state = await session_store.get(session_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    context = SessionContext.from_state(state)
    reply = await study_chat.respond(req.user_message, context)

    # persist both chat messages concurrently
    await asyncio.gather(
        session_store.append_chat(session_id, "user", req.user_message),
        session_store.append_chat(session_id, "assistant", reply),
    )

    return ChatResponse(reply=reply, current_question_index=state.current_question_index)


# ---------------------------------------------------------------------------
# main() kept for local pipeline testing only
# ---------------------------------------------------------------------------

"""async def main():
    pdf_bytes = Path("test_files/002-shortest-paths-1.pdf").read_bytes()

    processor = AsyncPDFProcessor()
    markdown, items, images = await processor.extract(pdf_bytes)

    image_filter = ImageFilter()
    filtered_images = await image_filter.heuristic_filter(images)
    filtered_images, descriptions = await image_filter.semantic_filter(filtered_images, markdown)

    text_filter = TextFilter()
    filtered_items = await text_filter.item_filter(items)

    concept_extractor = ConceptExtractor()
    scored_pages = await concept_extractor.score_pages(filtered_items)
    prompt_str = await concept_extractor.prioritize_content(filtered_items, scored_pages)

    print(prompt_str[:500])


asyncio.run(main())"""