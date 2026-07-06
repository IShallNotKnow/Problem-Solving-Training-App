from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status, Depends
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
from typing import Literal
from enum import Enum
from functools import lru_cache
from pydantic import BaseModel, HttpUrl, field_validator, model_validator

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class GenerationStatus(str, Enum):
    GENERATED = "generated"
    FAILED_VALIDATION = "failed_validation"

class Question(BaseModel):
    question_id: str
    question_type: Literal["MCQ", "FRQ"]
    difficulty: int
    topic: str
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
 
 
class QuestionResult(BaseModel):
    question_id: str
    score: float
    correct: bool
    feedback: str
    misconception: str | None = None
 
 
class QuestionValidationResult(BaseModel):
    question_id: str
    approved: bool
    feedback: str = ""
 
 
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
 
    def suggested_difficulty_delta(self) -> int:
        if self.avg_score >= 0.85:
            return +1
        if self.avg_score <= 0.4:
            return -1
        return 0
 
 
class GenerationResult(BaseModel):
    status: GenerationStatus
    questions: list[Question] = []
    validation: list[QuestionValidationResult] = []
    message: str = ""
 
 
class SessionState(BaseModel):
    session_id: str
    topic: str
    questions: list[Question] = []
    current_question_index: int = 0
    difficulty: int = 3
    consecutive_correct: int = 0
    consecutive_incorrect: int = 0
    answered_question_ids: list[str] = []
    history: list[QuestionResult] = []
    chat_history: list[dict] = []
 
    @property
    def current_question(self) -> Question | None:
        if 0 <= self.current_question_index < len(self.questions):
            return self.questions[self.current_question_index]
        return None
 
    def advance(self) -> None:
        self.current_question_index += 1
 
 
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
    topic: str
    content: str
    images: list[ImageInput] = []
    image_descriptions: dict[str, str] = {}
 
 
class AnswerRequest(BaseModel):
    question_id: str
    response: str
 
 
class ChatRequest(BaseModel):
    user_message: str
 
 
class AnswerResponse(BaseModel):
    feedback: str
    score: float
    new_difficulty: int
    misconception: str | None = None
 
 
class ChatResponse(BaseModel):
    reply: str
    current_question_index: int

    
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
                        "topic": {
                            "type": "string",
                            "description": "Short label for the specific concept being tested."
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
                        "question_id", "question_type", "difficulty", "topic",
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
                        }
                    },
                    "required": ["question_id", "score", "correct", "feedback"]
                }
            }
        },
        "required": ["results"]
    }
}

 
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
        for page in sorted_pages:
            page_items = [i for i in items if i["page"] == page]
            score = page_scores[page]
            has_priority_item = any(i.get("type") in self.ALWAYS_INCLUDE for i in page_items)
 
            if score > 3.0 or has_priority_item:
                page_text = "\n".join(i["md"] for i in page_items if i.get("md"))
                label = "[HIGH PRIORITY]" if score > 3.0 else "[CONTAINS KEY CONTENT]"
                result.append(f"{label} page {page}\n{page_text}")
 
        return "\n\n".join(result)


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
    def __init__(self):
        self.client = AsyncAnthropic()
        self.question_validator = QuestionValidator()
 
    async def _build_image_block(self, image: ImageInput) -> dict | None:
        async with httpx.AsyncClient() as http_client:
            try:
                img_response = await http_client.get(str(image.url))
                if img_response.status_code != 200:
                    return None
                base64_image = base64.b64encode(img_response.content).decode("utf-8")
                return {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.content_type,
                        "data": base64_image,
                    },
                }
            except Exception as e:
                print(f"Error fetching image {image.filename}: {e}")
                return None
 
    async def generate_questions(
        self,
        content: str,
        images: list[dict],
        image_descriptions: dict[str, str],
    ) -> GenerationResult:
        # Build base message content
        message_content: list[dict] = [{
            "type": "text",
            "text": (
                "You are a study assistant.\n\n"
                "Based on the following content and images, generate 20 study questions "
                "(10 MCQ, 10 FRQ) that test understanding of the key concepts and "
                "problem-solving skills.\n\n"
                f"Content:\n{content}\n\nImages:"
            ),
        }]
 
        # Convert to ImageInput and fetch in parallel
        image_inputs = [
            ImageInput(filename=img["filename"], url=img["url"], content_type=img["content_type"])
            for img in images
        ]
        image_blocks = await asyncio.gather(
            *(self._build_image_block(img) for img in image_inputs)
        )
 
        # Interleave image blocks and descriptions — zip over image_inputs so .filename works
        for i, (image, image_block) in enumerate(zip(image_inputs, image_blocks), start=1):
            if image_block is not None:
                message_content.append(image_block)
            description = image_descriptions.get(image.filename)
            if description:
                message_content.append({
                    "type": "text",
                    "text": f"Image {i} description:\n{description}",
                })
 
        approved = False
        attempts = 0
        MAX_RETRIES = 3
        questions: list[Question] = []
        validation: list[QuestionValidationResult] = []
        feedback_history: list[tuple[str, str]] = []
 
        while not approved and attempts < MAX_RETRIES:
            current_content = message_content.copy()
            if feedback_history:
                feedback_str = "\n".join(f"Question {qid}: {fb}" for qid, fb in feedback_history)
                current_content.append({
                    "type": "text",
                    "text": f"Previous attempt was rejected. Fix these issues:\n{feedback_str}",
                })
 
            message = await self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,  # 20 questions needs more room than 2048
                tools=[QUESTION_GENERATION_TOOL],
                tool_choice={"type": "tool", "name": "generate_questions"},
                messages=[{"role": "user", "content": current_content}],
            )
 
            tool_use = next((b for b in message.content if b.type == "tool_use"), None)
            if tool_use is None:
                raise RuntimeError("Model failed to return a tool call despite forced tool_choice")
 
            questions = [Question(**q) for q in tool_use.input["questions"]]
 
            seen_ids = {q.question_id for q in questions}
            if len(seen_ids) != len(questions):
                raise ValueError("Duplicate question_id in generated batch")
 
            validation = await self.question_validator.validate_questions(questions, content)
            approved = all(review.approved for review in validation)
            attempts += 1
 
            if not approved:
                feedback_history = [
                    (review.question_id, review.feedback)
                    for review in validation
                    if not review.approved
                ]
 
        return GenerationResult(
            status=GenerationStatus.GENERATED if approved else GenerationStatus.FAILED_VALIDATION,
            questions=questions,
            validation=validation,
        )


class AnswerValidator:
    def __init__(self):
        self.client = AsyncAnthropic()
 
    async def validate_answers(
        self,
        responses: list[dict],     # [{"question_id": "q1", "response": "..."}]
        questions: list[Question],
    ) -> AnswerValidationResult:
        valid_ids = {q.question_id for q in questions}
        unknown = [r["question_id"] for r in responses if r["question_id"] not in valid_ids]
        if unknown:
            raise ValueError(f"Responses reference unknown question_ids: {unknown}")
 
        # Build answer key from session questions — no need for the client to send it
        answer_key = [
            {
                "question_id": q.question_id,
                "correct_answer": q.correct_answer,
                "rubric_points": q.rubric_points,
            }
            for q in questions
            if q.question_id in {r["question_id"] for r in responses}
        ]
 
        payload = {
            "questions": [q.model_dump() for q in questions],
            "answer_key": answer_key,
            "student_responses": responses,
        }
 
        message = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            tools=[ANSWER_VALIDATION_TOOL],
            tool_choice={"type": "tool", "name": "submit_grading"},
            messages=[{
                "role": "user",
                "content": f"""You are grading a student's answers against an answer key.
 
For FRQs: grade for conceptual/procedural correctness, not exact string match.
Different variable names, equivalent algebraic forms, or alternate valid solution
paths should NOT be penalized. Only dock points for actual errors in reasoning,
method, or final result.
 
For MCQs: correct is binary (score 1.0 or 0.0).
 
Data:
{json.dumps(payload, indent=2)}
""",
            }],
        )
 
        tool_use = next(b for b in message.content if b.type == "tool_use")
        results = [QuestionResult(**r) for r in tool_use.input["results"]]
        return AnswerValidationResult(results=results)
    

class StudyChatAssistant:
    def __init__(self):
        self.client = AsyncAnthropic()
 
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


class DifficultyController:
    def __init__(self, up_streak: int = 2, down_streak: int = 2):
        self.up_streak = up_streak
        self.down_streak = down_streak
 
    def update(self, state: SessionState, result: QuestionResult) -> SessionState:
        if result.correct:
            state.consecutive_correct += 1
            state.consecutive_incorrect = 0
            if state.consecutive_correct >= self.up_streak:
                state.difficulty = min(5, state.difficulty + 1)
                state.consecutive_correct = 0
        else:
            state.consecutive_incorrect += 1
            state.consecutive_correct = 0
            if state.consecutive_incorrect >= self.down_streak:
                state.difficulty = max(1, state.difficulty - 1)
                state.consecutive_incorrect = 0
 
        state.history.append(result)
        return state

class SessionStore:
    def __init__(self):
        self._sessions: dict[str, SessionState] = {}
 
    def get_or_create(self, session_id: str, topic: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id, topic=topic)
        return self._sessions[session_id]
 
    def get(self, session_id: str) -> SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            raise KeyError(f"Session {session_id} not found")
        return state
 
    def save(self, session_id: str, state: SessionState) -> None:
        self._sessions[session_id] = state


@lru_cache
def get_question_generator() -> QuestionGenerator:
    return QuestionGenerator()

@lru_cache
def get_session_store() -> SessionStore:
    return SessionStore()

@lru_cache
def get_answer_validator() -> AnswerValidator:
    return AnswerValidator()

@lru_cache
def get_difficulty_controller() -> DifficultyController:
    return DifficultyController()

@lru_cache
def get_study_chat_assistant() -> StudyChatAssistant:
    return StudyChatAssistant()


@app.post("/sessions/{session_id}/generate", response_model=GenerationResult)
async def generate(
    session_id: str,
    req: GenerateRequest,
    question_generator: QuestionGenerator = Depends(get_question_generator),
    session_store: SessionStore = Depends(get_session_store),
):
    result = await question_generator.generate_questions(
        req.content, [img.model_dump() for img in req.images], req.image_descriptions
    )
    if result.status == GenerationStatus.GENERATED:
        state = session_store.get_or_create(session_id, topic=req.topic)
        state.questions = result.questions
        session_store.save(session_id, state)
        return result
    raise HTTPException(status_code=422, detail="Question generation failed validation after max retries")
 
 
@app.get("/sessions/{session_id}", response_model=SessionState)
async def get_session(
    session_id: str,
    session_store: SessionStore = Depends(get_session_store),
):
    try:
        return session_store.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
 
 
@app.post("/sessions/{session_id}/answer", response_model=AnswerResponse)
async def submit_answer(
    session_id: str,
    req: AnswerRequest,
    session_store: SessionStore = Depends(get_session_store),
    answer_validator: AnswerValidator = Depends(get_answer_validator),
    difficulty_controller: DifficultyController = Depends(get_difficulty_controller),
):
    try:
        state = session_store.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
 
    result = await answer_validator.validate_answers(
        [{"question_id": req.question_id, "response": req.response}],
        state.questions,
    )
    question_result = result.results[0]
    state = difficulty_controller.update(state, question_result)
    state.answered_question_ids.append(req.question_id)
    state.advance()
    session_store.save(session_id, state)
 
    return AnswerResponse(
        feedback=question_result.feedback,
        score=question_result.score,
        new_difficulty=state.difficulty,
        misconception=question_result.misconception,
    )
 
 
@app.post("/sessions/{session_id}/chat", response_model=ChatResponse)
async def chat(
    session_id: str,
    req: ChatRequest,
    session_store: SessionStore = Depends(get_session_store),
    study_chat: StudyChatAssistant = Depends(get_study_chat_assistant),
):
    try:
        state = session_store.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
 
    context = SessionContext.from_state(state)
    reply = await study_chat.respond(req.user_message, context)
    state.chat_history.append({"role": "user", "content": req.user_message})
    state.chat_history.append({"role": "assistant", "content": reply})
    session_store.save(session_id, state)
 
    return ChatResponse(reply=reply, current_question_index=state.current_question_index)



async def main():
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
 
 
asyncio.run(main())