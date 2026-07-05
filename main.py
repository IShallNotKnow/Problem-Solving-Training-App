from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from anthropic import Anthropic
from llama_cloud import AsyncLlamaCloud
from dotenv import load_dotenv
import os
from pathlib import Path
import asyncio
import httpx
import base64
from dataclasses import dataclass, field, asdict
import json
from typing import Literal
from enum import Enum

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

"""
@app.post("/sessions/{session_id}/generate")
async def generate(session_id: str, req: GenerateRequest):
    result = await question_generator.generate_questions(
        req.content, req.images, req.image_descriptions
    )
    session_store.save_questions(session_id, result.questions)
    return asdict_result(result)

@app.post("/sessions/{session_id}/answer")
async def submit_answer(session_id: str, req: AnswerRequest):
    state = session_store.get(session_id)
    result = await answer_validator.validate_answers([asdict(req)], state.questions)
    state = difficulty_controller.update(state, result.results[0])
    state.answered_question_ids.append(req.question_id)
    state.advance()
    session_store.save(session_id, state)

    return {
        "feedback": result.feedback,
        "score": result.score,
        "new_difficulty": state.difficulty,
    }


@app.post("/sessions/{session_id}/chat")
async def chat(session_id: str, req: ChatRequest):
    context = session_store.load_context(session_id)
    reply = await study_chat.respond(req.message, context)
    return {"reply": reply}
"""

class Difficulty(int, Enum):
    ONE = 1
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5

@dataclass
class Question:
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

    def __post_init__(self):
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
        else:
            raise ValueError(f"{self.question_id}: Invalid question type")

    @classmethod
    def from_dict(cls, d: dict) -> "Question":
        return cls(**d)

@dataclass
class QuestionResult:
    question_id: str
    score: float
    correct: bool
    feedback: str
    misconception: str | None = None


@dataclass
class QuestionValidationResult:
    question_id: str
    approved: bool
    feedback: str = ""

@dataclass
class AnswerValidationResult:
    results: list[QuestionResult]
    avg_score: float = field(init=False)

    def __post_init__(self):
        self.avg_score = sum(r.score for r in self.results) / len(self.results) if self.results else 0.0

    def suggested_difficulty_delta(self) -> int:
        if self.avg_score >= 0.85:
            return +1
        if self.avg_score <= 0.4:
            return -1
        return 0

class GenerationStatus(str, Enum):
    GENERATED = "generated"
    FAILED_VALIDATION = "failed_validation"

@dataclass
class GenerationResult:
    status: GenerationStatus
    questions: list[Question] = field(default_factory=list)
    validation: list[QuestionValidationResult] = field(default_factory=list)
    message: str = "" 

@dataclass
class SessionState:
    session_id: str
    topic: str
    questions: list[Question] = field(default_factory=list)   # the active batch
    current_question_index: int = 0
    difficulty: int = 3
    consecutive_correct: int = 0
    consecutive_incorrect: int = 0
    answered_question_ids: list[str] = field(default_factory=list)
    history: list[QuestionResult] = field(default_factory=list)
    chat_history: list[dict] = field(default_factory=list)

    @property
    def current_question(self) -> Question | None:
        if 0 <= self.current_question_index < len(self.questions):
            return self.questions[self.current_question_index]
        return None

    def advance(self) -> None:
        self.current_question_index += 1

@dataclass
class SessionContext:
    current_question: Question | None
    chat_history: list[dict]

    @classmethod
    def from_state(cls, state: SessionState) -> "SessionContext":
        return cls(
            current_question=state.current_question,
            chat_history=state.chat_history[-10:],  # cap context sent to the model
        )
    
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
                            "description": "Short label for the specific concept being tested, e.g. 'chain rule', 'variance vs std deviation'. Used to target weak areas in later questions."
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
                            "description": "MCQ: the correct choice text (redundant with index, kept for readability). FRQ: a complete, ideal model answer."
                        },
                        "rubric_points": {
                            "type": ["array", "null"],
                            "items": {"type": "string"},
                            "description": "FRQ only. 2-5 discrete, checkable points a correct answer must hit (not full sentences — short criteria, e.g. 'identifies the independent variable', 'correctly applies product rule'). Null for MCQ."
                        },
                        "explanation": {
                            "type": "string",
                            "description": "1-2 sentences on why the correct answer is right, shown to the student after grading. For MCQ, briefly note why the main distractor(s) are tempting but wrong."
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
    "description": "Review a batch of generated questions for correctness, difficulty accuracy, and quality, and flag any that need revision.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question_id": {
                            "type": "string",
                            "description": "Must match a question_id from the submitted batch."
                        },
                        "approved": {
                            "type": "boolean",
                            "description": "True only if the question is correct, unambiguous, at its stated difficulty, and actually tests problem-solving/understanding rather than rote recall or trivia."
                        },
                        "feedback": {
                            "type": ["string", "null"],
                            "description": "Required if approved is false. Specific, actionable instructions on what to fix — e.g. 'distractor B is actually also correct', 'rubric point 2 doesn't match what the prompt asks', 'this is a memorization question, rephrase to require applying the concept'. Null if approved."
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
                            "description": "0.0 (fully wrong) to 1.0 (fully correct). Use partial credit for FRQs — e.g. correct approach with a minor arithmetic slip, or an equivalent but differently-named solution, should score 0.6-0.9, not 0."
                        },
                        "correct": {
                            "type": "boolean",
                            "description": "True only if score >= 0.85"
                        },
                        "feedback": {
                            "type": "string",
                            "description": "1-3 sentences, specific to what the student wrote. If wrong, explain why. If correct via a different valid path, acknowledge it."
                        },
                        "misconception": {
                            "type": ["string", "null"],
                            "description": "Short tag for a recurring error type if present (e.g. 'sign error', 'confused variance/std-dev'), else null."
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
        self.client = AsyncLlamaCloud(
            api_key=os.getenv("LLAMA_CLOUD_API_KEY")
        )


    async def extract(self, file_bytes: bytes):
        uploaded = await self.client.files.create(
            file=("document.pdf", file_bytes, "application/pdf"),
            purpose="parse",
        )

        job = await self.client.parsing.parse(
            file_id=uploaded.id,
            tier="agentic",
            version="latest",
            expand=[
                "markdown",
                "items",
                "images_content_metadata",
            ],
            output_options={
                "images_to_save": ["layout", "embedded"],
            },
        )

        markdown = getattr(job, "markdown", "") or ""

        items = []
        for pages in getattr(getattr(job, "items", None), "pages", []):
            page_number = getattr(pages, "page_number", 0)
            for item in getattr(pages, "items", []):
                item_data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
                item_data["page_number"] = page_number

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
        self.exclude_types = {"logo", "icon", "banner", "header", "footer"}
        self.client = Anthropic()
    
    async def heuristic_filter(self, images: list) -> list:
        if not images:
            return None
        
        filtered = []
        for image in images:
            width = image["bbox"]["w"]
            height = image["bbox"]["h"]
            if image["content_type"] in self.exclude_types or height < 100 or width < 100:
                continue

            aspect_ratio = width/height
            if aspect_ratio > 10 or aspect_ratio < 0.1:
                continue

            filtered.append(image)
        
        return filtered
    
    async def semantic_filter(self, images: list, markdown: str) -> tuple[list[dict], dict[str, str]]:
        if not images:
            return []

        final_images = []
        descriptions = {}

        async with httpx.AsyncClient() as http_client:
            for image in images:
                try:
                    img_response = await http_client.get(image["url"])
                    if img_response.status_code != 200:
                        continue

                    base64_image = base64.b64encode(img_response.content).decode("utf-8")

                    result = self.client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=500,
                        temperature=0.0,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": image.get("content_type", "image/png"),
                                            "data": base64_image
                                        }
                                    },
                                    {
                                        "type": "text",
                                        "text": f"""Analyze these images from a lecture PDF.
First line: YES if it contains academically meaningful content (diagram, graph, 
mathematical figure, chart, technical illustration), NO if decorative or irrelevant.

If YES, second line onward: describe the academic content concisely, including any 
text, labels, or mathematical notation visible that may not appear in the lecture notes. 
If NO, stop after the first line."""
                                    }
                                ]
                            }
                        ]
                    )

                    response_text = result.content[0].text.strip()
                    first_line = response_text.split("\n")[0].upper()

                    if first_line == "YES":
                        final_images.append(image)

                        if "\n" in response_text:
                            descriptions[image["filename"]] = response_text.split("\n", 1)[1].strip()

                except Exception as e:
                    print(f"Error filtering image {image.get('filename')}: {e}")
                    final_images.append(image)  # keep on error, better to include than lose

        return final_images, descriptions


class TextFilter:
    def __init__(self):
        self.keep_types = {
            "paragraph", "heading", "equation", "table", "figure_caption", "list", "text", "code"
        }
    
    async def item_filter(self, items: list) -> list:
        if not items:
            return None

        return [item for item in items if item["type"] in self.keep_types]


class ConceptExtractor:
    def __init__(self):
        self.CONCEPT_SIGNALS = {
            "heading": 1.0,   # high signal
            "figure_caption": 0.8,
            "list": 0.7, #likely useful?, lists could denote purposes, code, etc. 
            "equation": 0.9,
            "code": 0.9,
            "table": 0.7,
            "paragraph": 0.3, # low signal individually, high in context
            "text": 0.2 #could be very informational, but too broad of a category
        }

        self.ALWAYS_INCLUDE = {"heading", "equation", "theorem", "definition", "code", "table"}


    async def score_pages(self, items: list) -> dict:
        page_scores = {}
        
        for item in items:
            page = item["page"]
            item_type = item.get("type", "")
            weight = self.CONCEPT_SIGNALS.get(item_type, 0)
            page_scores[page] = page_scores.get(page, 0) + weight
        
        return page_scores
    
    async def prioritize_content(self, items: list, page_scores: dict) -> str:
        sorted_pages = sorted(page_scores, key=page_scores.get, reverse=True)

        result = []
        for page in sorted_pages:
            page_items = [i for i in items if i["page"] == page]
            score = page_scores[page]

            has_priority_item = any(
                i.get("type") in self.ALWAYS_INCLUDE
                for i in page_items
            )

            if score > 3.0 or has_priority_item:
                page_text = "\n".join(i["md"] for i in page_items if i.get("md"))
                label = "[HIGH PRIORITY]" if score > 3.0 else "[CONTAINS KEY CONTENT]"
                result.append(f"{label} page {page}\n{page_text}")

        return "\n\n".join(result)


class QuestionGenerator:
    def __init__(self):
        self.client = Anthropic()
        self.questionValidator = QuestionValidator()

    async def build_images(self, image: dict):
        async with httpx.AsyncClient() as http_client:
            try:
                img_response = await http_client.get(image["url"])
                if img_response.status_code != 200:
                    return None

                base64_image = base64.b64encode(img_response.content).decode("utf-8")

                return {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.get("content_type", "image/png"),
                        "data": base64_image
                    },
                }
            
            except Exception as e:
                print(f"Error filtering image {image.get('filename')}: {e}")
                return None


    async def generate_questions(self, content: str, images: list, image_descriptions: dict) -> dict:
        message_content = [
            {
                "type": "text",
                "text": f"""
    You are a study assistant.

    Based on the following content and images, generate 20 study questions
    (10 MCQ, 10 FRQ, separated by ```) that test understanding of the key concepts and
    problem-solving skills. Alongside this, provide answers (separated by ```) after the 
    questions in the same structure.

    Content:
    {content}

    Images:
    """
            }
        ]

        image_blocks = await asyncio.gather(
            *(self.build_images(img) for img in images)
        )

        for i, (image, image_block) in enumerate(zip(images, image_blocks), start=1):
            description = image_descriptions.get(image["filename"])
            if image_block is not None:
                message_content.append(image_block)

            if description:
                message_content.append(
                    {
                        "type": "text",
                        "text": f"Image {i} description:\n{description}"
                    }
                )
            
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
                    "text": f"Previous attempt was rejected. Fix these issues:\n{feedback_str}"
                })

            message = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                tools=[QUESTION_GENERATION_TOOL],
                tool_choice={"type": "tool", "name": "create_questions"},
                messages=[{"role": "user", "content": current_content}]
            )

            tool_use = next((b for b in message.content if b.type == "tool_use"), None)
            if tool_use is None:
                # Shouldn't happen when forced, but don't let it crash silently either
                raise RuntimeError("Model failed to return a tool call despite forced tool_choice")

            questions = [Question.from_dict(q) for q in tool_use.input["questions"]]

            seen_ids = {q.question_id for q in questions}
            if len(seen_ids) != len(questions):
                raise ValueError("Duplicate question_id in generated batch")

            validation = await self.questionValidator.validate_questions(questions, content)
            approved = all(review.approved for review in validation)
            attempts += 1

            if not approved:
                feedback_history = [
                    (review.question_id, review.feedback)
                    for review in validation if not review.approved
                ]

        return GenerationResult(
            status=GenerationStatus.GENERATED if approved else GenerationStatus.FAILED_VALIDATION,
            questions=questions,
            validation=validation,
        )


class QuestionValidator:
    def __init__(self):
        self.client = Anthropic()
    
    async def validate_questions(
            self, questions: list[dict], 
            content: str, 
            image_descriptions: dict[str, str] | None = None
        ) -> list[QuestionValidationResult]:

        if not questions:
            return []
        
        descriptions_block = ""
        if image_descriptions:
            descriptions_block = "\n\nImage descriptions (source material included images):\n" + "\n".join(
                f"- {filename}: {desc}"
                for filename, desc in image_descriptions.items()
            )
        
        message = self.client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        tools=[QUESTION_VALIDATION_TOOL],
        tool_choice={"type": "tool", "name": "validate_questions"},
        messages=[
            {
                "role": "user",
                "content": f"""You are a study question validator. Evaluate the following questions against the source content.

For each question assess:
- Correctness: is `correct_answer` (and `rubric_points` for FRQ) actually correct given the content?
- Relevance: is it directly testable from the content?
- Depth: does it test understanding or problem-solving rather than rote recall?
- Clarity: is it unambiguous and self-contained without needing the original material?
- Difficulty accuracy: does the actual difficulty of the question match its stated `difficulty` (1-5)?
- MCQ only: are `choices` plausible distractors, with exactly one clearly correct option at `correct_choice_index`?
- FRQ only: do `rubric_points` fully and precisely capture what a correct answer must contain?

Source content:
{content}{descriptions_block}

Questions (full generated objects, including answers and rubrics):
{json.dumps([asdict(q) for q in questions], indent=2)}
"""
            }
        ]
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


class AnswerValidator:
    def __init__(self):
        self.client = Anthropic()

    async def validate_answers(
        self,
        responses: list[dict],   # [{"question_id": "q1", "response": "..."}, ...]
        questions: list[dict],   # [{"question_id": "q1", "type": "FRQ", "prompt": "..."}, ...]
        answer_key: list[dict],  # [{"question_id": "q1", "answer": "...", "rubric": "..."}, ...]
    ) -> AnswerValidationResult:
        
        valid_ids = {q.question_id for q in questions}
        unknown = [r["question_id"] for r in responses if r["question_id"] not in valid_ids]
        if unknown:
            raise ValueError(f"Responses reference unknown question_ids: {unknown}")

        payload = {
            "questions": questions,
            "answer_key": answer_key,
            "student_responses": responses,
        }

        message = self.client.messages.create(
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

For MCQs: correct is binary (score 1.0 or 0.0) unless the question allows
multi-select partial credit.

Data:
{json.dumps(payload, indent=2)}
"""
            }]
        )

        tool_use = next(b for b in message.content if b.type == "tool_use")
        results = [QuestionResult(**r) for r in tool_use.input["results"]]
        return AnswerValidationResult(results=results)
    
class StudyChatAssistant:
    """Handles clarifications, conversational asides, 'why do I need this' —
    anything that isn't a generation request. No tools, plain text in/out."""
    def __init__(self):
        self.client = Anthropic()

    async def respond(self, user_message: str, session_context: SessionContext) -> str:
        message = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": f"""You are a study assistant helping a student work through practice questions.

Current question the student is looking at:
{json.dumps(asdict(session_context.current_question), indent=2)}

Recent conversation:
{session_context.chat_history}

Student's message: {user_message}

Answer conversationally. If they're asking for a hint, guide them without giving
away the full answer. If they're asking a concept question, explain clearly."""
            }]
        )
        return next(b.text for b in message.content if b.type == "text")


class DifficultyController:
    """Deterministic staircase. No LLM involved."""

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

    def save(self, session_id: str, state: SessionState) -> None:
        self._sessions[session_id] = state


async def main():
    pdf_bytes = Path("test_files/002-shortest-paths-1.pdf").read_bytes()

    processor = AsyncPDFProcessor()
    markdown, items, images = await processor.extract(pdf_bytes)

    imageFilter = ImageFilter()
    filtered_images = await imageFilter.heuristic_filter(images)

    # print(len(images))
    # print(len(filtered_images))
    # print([image["url"] for image in filtered_images])
    
    textFilter = TextFilter()
    filtered_items = await textFilter.item_filter(items)

    # print(len(items))
    # print(len(filtered_items))

    # print([item for item in items if item not in filtered_items])
    # print([item for item in items if item.get("type") == "handwriting"])

    conceptExtractor = ConceptExtractor()
    scored_pages = await conceptExtractor.score_pages(filtered_items)
    prompt_str = await conceptExtractor.prioritize_content(filtered_items, scored_pages)

    # print(scored_pages)
    # print(prompt_str)


asyncio.run(main())