from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    label: str | None = None


class GenerationStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    GENERATED = "generated"
    FAILED_VALIDATION = "failed_validation"


class Question(BaseModel):
    id: UUID | None = None  # internal db uuid, null when model-generated
    question_id: str  # model-generated, unique within study_set + generation_input
    study_set_id: UUID | None = None  # which study set owns this question
    generation_input_id: UUID | None = None  # which generation run produced this question
    question_type: Literal["MCQ", "FRQ"]
    topic_difficulties: dict[str, int]
    prompt: str
    correct_answer: str
    explanation: str
    choices: list[str] | None = None
    correct_choice_index: int | None = None
    rubric_points: list[str] | None = None
    # position and scheduling state removed — now in session_questions and question_scheduling

    @property
    def topics(self) -> list[str]:
        return list(self.topic_difficulties.keys())

    @property
    def difficulty(self) -> float:
        return sum(self.topic_difficulties.values()) / len(self.topic_difficulties)

    @model_validator(mode="after")
    def validate_question_type(self) -> "Question":
        if not self.topic_difficulties:
            raise ValueError(f"{self.question_id}: topic_difficulties must not be empty")
        for topic, difficulty in self.topic_difficulties.items():
            if not (300 <= difficulty <= 3000):
                raise ValueError(
                    f"{self.question_id}: difficulty for topic '{topic}' must be between 300 and 3000"
                )
        if self.question_type == "MCQ":
            if not self.choices or len(self.choices) < 3:
                raise ValueError(f"{self.question_id}: MCQ requires >=3 choices")
            if self.correct_choice_index is None or not (
                0 <= self.correct_choice_index < len(self.choices)
            ):
                raise ValueError(f"{self.question_id}: invalid correct_choice_index")
        elif self.question_type == "FRQ":
            if not self.rubric_points:
                raise ValueError(f"{self.question_id}: FRQ requires rubric_points")
            if self.choices:
                raise ValueError(f"{self.question_id}: FRQ should not have choices")
        return self


class SessionQuestion(BaseModel):
    """Join table row — the scheduler's selection for one session."""

    id: UUID
    session_id: UUID
    question_id: UUID  # references questions(id)
    position: int
    source: Literal["generated", "resurfaced"]
    status: Literal["unseen", "active", "mastered", "due"]
    question: Question | None = None  # populated when loaded with join


class QuestionScheduling(BaseModel):
    """FSRS state per user-question pair."""

    id: UUID | None = None
    user_id: UUID
    question_id: UUID
    due_at: datetime | None = None
    stability: float = 0.0
    difficulty: float = 0.3
    retrievability: float = 1.0
    times_seen: int = 0
    last_attempted_at: datetime | None = None


class TopicResult(BaseModel):
    topic: str
    score: float
    correct: bool
    feedback: str = ""
    confidence: float = 1.0
    adaptation_signal: float = 0.0
    misconception: str | None = None


class TopicUpdate(BaseModel):
    topic: str
    previous_elo: int
    new_elo: int
    elo_delta: float
    previous_p_known: float
    new_p_known: float
    reason: str = ""


class QuestionResult(BaseModel):
    question_id: str
    score: float
    correct: bool
    feedback: str
    topic_results: list[TopicResult] = Field(default_factory=list)
    misconception: str | None = None


class QuestionValidationResult(BaseModel):
    question_id: str
    approved: bool
    feedback: str = ""


class TopicStats(BaseModel):
    topic: str
    attempts: int = 0
    elo: int = 800
    p_known: float = 0.5


class TopicEvidence(BaseModel):
    topic: str
    expected_score: float
    actual_score: float
    elo_delta: float
    p_obs: float
    adaptation_signal: float
    misconception: str | None = None


class AnswerValidationResult(BaseModel):
    results: list[QuestionResult]


class GenerationResult(BaseModel):
    status: GenerationStatus
    questions: list[Question] = Field(default_factory=list)
    validation: list[QuestionValidationResult] = Field(default_factory=list)
    message: str = ""


class SessionState(BaseModel):
    session_id: UUID
    study_set_id: UUID | None = None  # which study set this session draws from
    label: str
    current_position: int = 0  # renamed from current_question_index — position in session_questions
    topic_stats: dict[str, TopicStats] = Field(default_factory=dict)
    questions: list[Question] = Field(default_factory=list)  # loaded via session_questions join
    history: list[QuestionResult] = Field(default_factory=list)
    chat_history: list[dict] = Field(default_factory=list)
    created_at: datetime | None = None

    @property
    def current_question(self) -> Question | None:
        if 0 <= self.current_position < len(self.questions):
            return self.questions[self.current_position]
        return None

    @property
    def questions_count(self) -> int:
        return len(self.questions)

    def advance(self) -> None:
        self.current_position += 1

    def get_topic_elo(self, topics: list[str]) -> dict:
        return {t: self.topic_stats[t].elo if t in self.topic_stats else 800 for t in topics}

    def topic_profile(self, min_attempts: int = 2) -> dict:
        strong, weak, unseen = [], [], []
        for topic, stats in self.topic_stats.items():
            if stats.attempts >= min_attempts:
                if stats.p_known >= 0.7:
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


class GenerateRequest(BaseModel):
    label: str
    raw_markdown: str = ""
    topic_profile: dict | None = None


class AnswerRequest(BaseModel):
    question_id: str
    response: str | None = None
    choice_index: int | None = None


class ChatRequest(BaseModel):
    user_message: str

    @field_validator("user_message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("user_message cannot be empty")
        return v


class AnswerResponse(BaseModel):
    feedback: str
    score: float
    topic_stats: dict[str, TopicStats]
    topic_updates: list[TopicUpdate]
    misconception: str | None = None


class ChatResponse(BaseModel):
    reply: str
    current_position: int  # renamed from current_question_index


class StudySetSummary(BaseModel):  # new — for listing study sets
    study_set_id: UUID
    label: str
    created_at: datetime | None = None
    question_count: int = 0
    generation_count: int = 0


class UploadResponse(BaseModel):
    study_set_id: UUID  # upload now returns study_set_id, not session_id
    generation_input_id: UUID
    content: str
    raw_markdown: str
    pdf_path: str


class SessionSummary(BaseModel):
    session_id: UUID
    study_set_id: UUID | None = None
    label: str
    current_position: int = 0  # renamed
    last_active_at: datetime | None = None
    created_at: datetime | None = None


class QuestionDTO(BaseModel):
    id: UUID | None = None  # internal uuid — needed for answer_attempts FK
    question_id: str
    question_type: Literal["MCQ", "FRQ"]
    prompt: str
    choices: list[str] | None = None
    topic_difficulties: dict[str, int]
    position: int = 0  # from session_questions.position
    status: str = "unseen"  # from session_questions.status


class GenerationResultDTO(BaseModel):
    status: GenerationStatus
    questions: list[QuestionDTO]
    validation: list[QuestionValidationResult]
    message: str = ""


class SessionStateDTO(BaseModel):
    session_id: UUID
    study_set_id: UUID | None = None
    label: str
    current_position: int = 0
    topic_stats: dict[str, TopicStats] = Field(default_factory=dict)
    questions: list[QuestionDTO] = Field(default_factory=list)
    history: list[QuestionResult] = Field(default_factory=list)
    chat_history: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Tool schemas — unchanged
# ---------------------------------------------------------------------------

QUESTION_GENERATION_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_questions",
        "description": "Submit a batch of generated study questions with answers and grading rubrics.",
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question_id": {
                                "type": "string",
                                "description": "Unique short id, e.g. 'q1', 'q2'.",
                            },
                            "question_type": {"type": "string", "enum": ["MCQ", "FRQ"]},
                            "topic_difficulties": {
                                "type": "object",
                                "description": (
                                    "Maps each tested topic to its target ELO difficulty "
                                    "(300=novice recall, 1650=intermediate application, "
                                    "3000=expert synthesis). Each key must exactly match "
                                    "an entry in the session's topic list. Synthesis "
                                    "questions must include one entry per combined topic."
                                ),
                                "additionalProperties": {
                                    "type": "integer",
                                    "minimum": 300,
                                    "maximum": 3000,
                                },
                                "minProperties": 1,
                            },
                            "prompt": {
                                "type": "string",
                                "description": "The question text shown to the student. "
                                "Use GitHub-flavoured markdown. Bold key terms, "
                                "use code blocks for identifiers, LaTeX for equations.",
                            },
                            "choices": {
                                "type": ["array", "null"],
                                "items": {"type": "string"},
                                "minItems": 3,
                                "maxItems": 5,
                                "description": (
                                    "MCQ only. 3-5 answer options, using GitHub-flavoured markdown. "
                                    "Bold key terms, use code blocks for identifiers, LaTeX for equations. "
                                    "No leading letters like 'A)'. Null for FRQ."
                                ),
                            },
                            "correct_choice_index": {
                                "type": ["integer", "null"],
                                "description": (
                                    "MCQ only. 0-based index into `choices` "
                                    "for the correct answer. Null for FRQ."
                                ),
                            },
                            "correct_answer": {
                                "type": "string",
                                "description": (
                                    "ALWAYS required — never omit this field. "
                                    "MCQ: copy the exact text of the correct choice from `choices` verbatim. "
                                    "FRQ: write a complete model answer that fully satisfies all rubric_points. "
                                    "Use GitHub-flavoured markdown. Bold key terms, use code blocks for identifiers, LaTeX for equations."
                                ),
                            },
                            "rubric_points": {
                                "type": ["array", "null"],
                                "items": {"type": "string"},
                                "description": (
                                    "FRQ only. 2-5 discrete, checkable points "
                                    "a correct answer must hit. Null for MCQ."
                                ),
                            },
                            "explanation": {
                                "type": "string",
                                "description": (
                                    "Required. 1-2 sentences shown to the student after "
                                    "grading explaining why the correct answer is right. "
                                    "For MCQ also explain why the distractors are wrong. "
                                    "For FRQ summarise the key insight a correct answer must show."
                                    "Detailed response using GitHub-flavoured markdown. "
                                    "Bold key terms, use code blocks for identifiers, LaTeX for equations."
                                ),
                            },
                        },
                        "required": [
                            "question_id",
                            "question_type",
                            "topic_difficulties",
                            "prompt",
                            "correct_answer",
                            "explanation",
                            "choices",
                            "correct_choice_index",
                            "rubric_points",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["questions"],
            "additionalProperties": False,
        },
    },
}

QUESTION_VALIDATION_TOOL = {
    "type": "function",
    "function": {
        "name": "validate_questions",
        "strict": True,
        "description": "Review a batch of generated questions for correctness, difficulty accuracy, and quality.",
        "parameters": {
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
                                "description": (
                                    "True only if the question is correct, "
                                    "unambiguous, at its stated difficulty, "
                                    "and tests understanding rather than rote recall."
                                ),
                            },
                            "feedback": {
                                "type": ["string", "null"],
                                "description": (
                                    "Required if approved is false. "
                                    "Specific, actionable fix instructions. "
                                    "Null if approved."
                                ),
                            },
                        },
                        "required": ["question_id", "approved", "feedback"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["reviews"],
            "additionalProperties": False,
        },
    },
}

ANSWER_VALIDATION_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_grading",
        "strict": True,
        "description": "Submit graded results for each student response.",
        "parameters": {
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
                                "minimum": 0.0,
                                "maximum": 1.0,
                                "description": (
                                    "0.0 (fully wrong) to 1.0 (fully correct). "
                                    "Use partial credit for FRQs."
                                ),
                            },
                            "correct": {
                                "type": "boolean",
                                "description": "True only if score >= 0.85",
                            },
                            "feedback": {
                                "type": "string",
                                "description": "1-3 sentences specific to what the student wrote. "
                                "Detailed feedback using GitHub-flavoured markdown. Bold key terms, "
                                "use code blocks for identifiers, LaTeX for equations.",
                            },
                            "misconception": {
                                "type": ["string", "null"],
                                "description": "Short tag for a recurring error type if present, else null.",
                            },
                            "topic_results": {
                                "type": "array",
                                "minItems": 1,
                                "description": (
                                    "Per-topic breakdown. One entry per topic in "
                                    "topic_difficulties. Required for all questions."
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "topic": {
                                            "type": "string",
                                            "description": (
                                                "Copy this value exactly as it appears in the "
                                                "topic_difficulties keys of the grading_data — "
                                                "do not rephrase, translate, or alter punctuation."
                                            ),
                                        },
                                        "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                                        "correct": {"type": "boolean"},
                                        "confidence": {
                                            "type": "number",
                                            "minimum": 0.0,
                                            "maximum": 1.0,
                                        },
                                        "adaptation_signal": {
                                            "type": "number",
                                            "minimum": -1.0,
                                            "maximum": 1.0,
                                        },
                                        "misconception": {"type": ["string", "null"]},
                                        "feedback": {"type": "string"},
                                    },
                                    "required": [
                                        "topic",
                                        "score",
                                        "correct",
                                        "confidence",
                                        "adaptation_signal",
                                        "misconception",
                                        "feedback",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": [
                            "question_id",
                            "score",
                            "correct",
                            "feedback",
                            "misconception",
                            "topic_results",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["results"],
            "additionalProperties": False,
        },
    },
}

IMAGE_FILTERING_TOOL = {
    "type": "function",
    "function": {
        "name": "filter_images",
        "strict": True,
        "description": "Semantically filter images based on their relation to a lecture PDF.",
        "parameters": {
            "type": "object",
            "properties": {
                "filtered_images": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "keep": {
                                "type": "boolean",
                                "description": (
                                    "True if the image contains academically meaningful "
                                    "content. False if it is decorative or irrelevant."
                                ),
                            },
                            "description": {
                                "type": ["string", "null"],
                                "description": "Concise description of the academic content. Null if keep is false.",
                            },
                        },
                        "required": ["keep", "description"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["filtered_images"],
            "additionalProperties": False,
        },
    },
}
