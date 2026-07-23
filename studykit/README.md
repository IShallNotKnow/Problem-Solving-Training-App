# Problem Solving Training App

# studykit

An AI-powered study tool that turns your lecture slides or notes into adaptive practice questions. Upload a PDF, get 20 questions (MCQ + free-response), answer them, and watch the system adjust difficulty based on how you're actually doing.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Browser (React)                         │
│                                                                 │
│  Dashboard ──► StudyPage                                        │
│                   │                                             │
│                   ├── upload PDF / paste notes                  │
│                   ├── answer MCQ (click) / FRQ (type)           │
│                   └── chat assistant (hints, explanations)      │
└────────────────────────┬────────────────────────────────────────┘
                         │ REST + JWT (Supabase auth)
┌────────────────────────▼────────────────────────────────────────┐
│                      FastAPI backend                            │
│                                                                 │
│  /upload ──► LlamaCloud (PDF parse) ──► ImageFilter            │
│                                         ConceptExtractor        │
│                                              │                  │
│  /generate ──────────────────────────────────► QuestionGenerator│
│                                               QuestionValidator │
│                                                                 │
│  /answer ──► AnswerValidator (FRQ: LLM, MCQ: deterministic)     │
│              DifficultyController (ELO + BKT)                   │
│                                                                 │
│  /chat ──► StudyChatAssistant                                   │
└──────┬───────────────────────────────────────────────┬──────────┘
       │                                               │
┌──────▼──────┐                              ┌─────────▼────────┐
│  Anthropic  │                              │     Supabase     │
│  claude-    │                              │                  │
│  haiku-4-5  │                              │  PostgreSQL      │
│             │                              │  Storage (PDFs,  │
│  - filter   │                              │  images)         │
│  - generate │                              │  Auth (JWT)      │
│  - validate │                              │  RLS policies    │
│  - grade    │                              └──────────────────┘
│  - chat     │
└─────────────┘
```

### Key data flow

1. **Upload** — PDF bytes → LlamaCloud (LlamaParse agentic tier) → structured markdown + image metadata. Images are heuristically filtered (size, aspect ratio, category), then semantically filtered via Claude Haiku (keep/discard + description). Relevant text is scored by page and truncated to fit context limits.

2. **Generate** — Extracted content + images → Claude Haiku via forced tool use → 20 questions (10 MCQ, 10 FRQ). A second Haiku call validates each question for correctness, relevance, and difficulty accuracy. Rejected questions are regenerated with feedback, up to 3 attempts. Topic difficulty is expressed as ELO ratings (300–3000) per question.

3. **Answer** — MCQ answers are graded deterministically (choice index equality check, no LLM call). FRQ answers go to Claude Haiku which returns a score, feedback, per-topic confidence, and an adaptation signal. The difficulty controller updates ELO and BKT state per topic.

4. **Chat** — Stateless per turn. The full current question (including answer key) is injected into the system prompt server-side only; the frontend never sees it.

---

## Adaptive difficulty engine

### ELO (per-topic skill rating)

Each topic tracked in a session has an ELO rating initialised at 1500. After each answer:

```
expected = 1 / (1 + 10^((question_elo - student_elo) / 400))
K         = K_BASE × confidence × (0.5 + 0.5 × p_known) × adaptation_scale
elo_delta = K × (actual_score - expected_score)
```

- `confidence` (0–1) from the LLM grader scales K down when the grader is uncertain — partial answers don't move ELO as much as clear ones.
- `adaptation_signal` (-1 to +1) from the grader scales K by `clamp(1 + signal, 0.25, 2.0)`. A strong misconception doubles the update; a borderline answer halves it. The clamp preserves direction: a correct answer always increases ELO regardless of signal.

### BKT (Bayesian Knowledge Tracing)

ELO measures relative difficulty; BKT tracks the probability the student has actually learned a topic (`p_known`), accounting for slip and guess:

```
P(correct | known)   = 1 - P_SLIP   (0.9)
P(correct | unknown) = P_GUESS      (0.1)
p_posterior          = p_known × P(correct|known) / P(correct)
p_known_new          = p_posterior × (1 - P_FORGET) + (1 - p_posterior) × P_LEARN
```

`p_known` is used to weight K: topics the student has not yet learned get larger ELO swings. Both metrics feed `topic_profile()` which buckets topics into strong / weak / unseen and biases the next generation round.

---

## Setup

### Prerequisites

- Python 3.11+
- Node 18+
- A [Supabase](https://supabase.com) project
- An [Anthropic](https://console.anthropic.com) API key
- A [LlamaCloud](https://cloud.llamaindex.ai) API key
- Valkey or Redis (for rate limiting)

### Backend

```bash
# 1. Clone and install
git clone https://github.com/you/Problem-Solving-Training-App
cd studykit
pip install -e ".[dev]"

# 2. Environment
cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY,
# ANTHROPIC_API_KEY, LLAMA_CLOUD_API_KEY

# 3. Database
# Run the migrations in /backend/supabase/migrations against your Supabase project
# (via supabase CLI or the Supabase dashboard SQL editor)

# 4. Start
uvicorn backend.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
# Fill in VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, VITE_API_BASE_URL
npm run dev
```

### Environment variables

| Variable | Where | Description |
|---|---|---|
| `SUPABASE_URL` | backend | Project URL from Supabase dashboard |
| `SUPABASE_ANON_KEY` | backend | Anon/public key |
| `SUPABASE_SERVICE_ROLE_KEY` | backend | Service role key (storage only) |
| `ANTHROPIC_API_KEY` | backend | claude-haiku-4-5 access |
| `LLAMA_CLOUD_API_KEY` | backend | LlamaParse agentic tier |
| `VALKEY_URL` | backend | `redis://localhost:6379` by default |
| `VITE_SUPABASE_URL` | frontend | Same as backend |
| `VITE_SUPABASE_ANON_KEY` | frontend | Same as backend |
| `VITE_API_BASE_URL` | frontend | `http://localhost:8000` locally |

---

## Database schema (overview)

```
sessions          — one per study set, tracks current_question_index
questions         — 20 per session, position-ordered, answer key stored server-side
answer_attempts   — one row per submission, idempotent on question_id
topic_stats       — ELO + p_known + attempts per topic per session
elo_history       — per-question ELO snapshots for replay
chat_messages     — rolling window, last 10 turns served to client
generation_inputs — extracted PDF content + image refs
generation_images — stored image metadata, joined through generation_inputs
generation_topics — topics covered per generation round (for profile building)
```

Row-level security is enabled on all tables. The backend uses two Supabase clients: a per-request anon client (user JWT, RLS enforced) for all table queries, and a service role client for storage operations only.

---

## Trade-offs and honest limitations

**LLM grading is approximate.** FRQ scoring relies on Claude Haiku, which can be overgenerous with partial credit or miss nuanced errors. Confidence scores partially compensate but don't eliminate this. MCQ grading is deterministic and exact.

**Single-process rate limiting.** `slowapi` uses an in-process counter backed by Valkey. Correct under a single worker; would need sticky sessions or a shared counter under multiple workers.

**Session locks are in-process.** `_session_locks` (a `defaultdict` of `asyncio.Lock`) prevents concurrent writes within one process but not across multiple workers. The answer submission path is the highest risk; the correct fix is to move the read-modify-write into a transactional Postgres RPC (see `submit_answer` in the Postgres functions).

**No streaming.** Generation and answer validation block until Claude returns a full response. Generation takes 10–20 seconds for 20 questions with validation. Streaming tool use would improve perceived latency.

**PDF size cap is 10 MB.** LlamaCloud's agentic parser is slow on large documents; the cap keeps p95 latency reasonable. Dense 200-page textbooks will hit content truncation at 12,000 chars.

**Image token budget.** Images exceeding `MAX_PROMPT_IMAGE_TOKENS` (20k tokens estimated) fall back to text descriptions. Token estimation is a rough pixel-area heuristic, not an exact count.

**No spaced repetition scheduling.** The adaptive engine reweights question generation toward weak topics but doesn't implement a full SRS scheduler (SM-2, FSRS). `p_known` with the forgetting factor (`P_FORGET = 0.05`) is a lightweight proxy.

---

## Project structure

```
studykit/
├── README.md
├── pyproject.toml
├── backend/
│   ├── main.py              # FastAPI app, endpoints, business logic
│   ├── models.py            # Pydantic models, tool schemas
│   ├── .env.example
│   ├── auth.py              # JWT verification
│   ├── config.py            # Pydantic Settings
│   └── supabase/
│       └── migrations/      # SQL migrations + RPC functions
└── frontend/
    ├── src/
    │   ├── pages/
    │   │   ├── Dashboard.jsx
    │   │   └── StudyPage.jsx
    │   ├── context/
    │   │   ├── AuthContext.jsx
    │   │   ├── ThemeContext.jsx
    │   │   └── ToastContext.jsx
    │   └── utils/
    │       └── api.js
    ├── package.json   
    ├── .env.example
    └── eslint.config.js
```