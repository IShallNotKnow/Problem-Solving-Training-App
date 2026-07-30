# Studykit

An AI-powered study tool that turns lecture slides or notes into adaptive practice questions. Upload a PDF or paste your notes, get 20 questions (MCQ + free-response), and watch the system adjust difficulty based on how you're actually doing — not just what you got right, but how confidently and how recently.

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
│  /generate ──► enqueue ──────────────────────► ARQ worker       │
│                                               QuestionGenerator │
│                                               QuestionValidator │
│                                                                 │
│  /answer ──► AnswerValidator (FRQ: LLM, MCQ: deterministic)     │
│              DifficultyController (ELO + BKT)                   │
│                                                                 │
│  /chat ──► StudyChatAssistant                                   │
└──────┬──────────────────────────┬────────────────┬─────────────┘
       │                          │                │
┌──────▼──────┐         ┌─────────▼──────┐  ┌─────▼────────────┐
│   OpenAI    │         │    Supabase    │  │     Valkey       │
│  gpt-5-mini │         │                │  │                  │
│             │         │  PostgreSQL    │  │  Job queue       │
│  - filter   │         │  Storage       │  │  Session locks   │
│  - generate │         │  Auth (JWT)    │  │  Rate limiting   │
│  - validate │         │  RLS policies  │  └──────────────────┘
│  - grade    │         └────────────────┘
│  - chat     │
└─────────────┘
```

### Key data flow

1. **Upload** — PDF bytes → LlamaCloud (LlamaParse agentic tier) → structured markdown + image metadata. Images are heuristically filtered (size, aspect ratio, category), then semantically filtered via GPT-5 Mini vision (keep/discard + description). Relevant text is scored by page using content-type signals and truncated to fit context limits while preserving the highest-signal material.

2. **Generate** — The API enqueues a job and returns a `job_id` immediately (202). An ARQ worker picks it up: extracted content + images → GPT-5 Mini via forced tool use → 20 questions (10 MCQ, 10 FRQ). A second model call validates each question for correctness, relevance, and difficulty accuracy. Rejected questions are regenerated with structured feedback, up to 3 rounds. Topic difficulty is expressed as ELO ratings (300–3000) per question. The client polls `/generate/{job_id}` until complete.

3. **Answer** — MCQ answers are graded deterministically (choice index equality, no LLM call). FRQ answers go to GPT-5 Mini which returns a score, feedback, per-topic confidence, and an adaptation signal. The difficulty controller updates ELO and BKT state per topic, then writes atomically via a `SECURITY DEFINER` RPC.

4. **Chat** — Stateless per turn. The full current question (including answer key) is injected into the developer prompt server-side only — the frontend never sees it.

---

## Adaptive difficulty engine

### ELO (per-topic skill rating)

Each topic tracked in a session has an ELO rating initialised at 1500. After each answer:

```
expected        = 1 / (1 + 10^((question_elo - student_elo) / 400))
K               = K_BASE × confidence × (0.5 + 0.5 × p_known) × adaptation_scale
elo_delta       = K × (actual_score - expected_score)
adaptation_scale = clamp(1 + adaptation_signal, 0.25, 2.0)
```

- `confidence` (0–1) from the LLM grader scales K down when the grader is uncertain — partial answers don't move ELO as much as clear ones.
- `adaptation_signal` (−1 to +1) from the grader scales K by up to 2×. A strong misconception doubles the update; a borderline answer halves it. The clamp preserves direction: a correct answer always increases ELO regardless of signal.

### BKT (Bayesian Knowledge Tracing)

ELO measures relative performance against question difficulty. BKT separately tracks the probability the student has genuinely learned a topic (`p_known`), accounting for slip and guess:

```
P(correct | known)   = 1 − P_SLIP   (0.9)
P(correct | unknown) = P_GUESS      (0.1)
p_posterior          = p_known × P(correct|known) / P(correct)
p_known_new          = p_posterior × (1 − P_FORGET) + (1 − p_posterior) × P_LEARN
```

`p_known` weights K so that topics the student hasn't internalised get larger ELO swings per attempt. Both metrics feed `topic_profile()`, which buckets topics into strong / weak / unseen and biases the next generation round toward weak areas — ensuring follow-up sessions address gaps rather than rehashing what's already solid.

---

## Setup

### Prerequisites

- Python 3.11+
- Node 18+
- A [Supabase](https://supabase.com) project
- An [OpenAI](https://platform.openai.com) API key
- A [LlamaCloud](https://cloud.llamaindex.ai) API key
- Valkey or Redis

### Backend

```bash
# 1. Clone and install
git clone https://github.com/you/studykit
cd studykit
pip install -e ".[dev]"

# 2. Environment
cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY,
# OPENAI_API_KEY, LLAMA_CLOUD_API_KEY, VALKEY_URL

# 3. Database
# Run the migrations in /backend/supabase/migrations against your Supabase project
# via the Supabase CLI or the SQL editor in the dashboard

# 4. Start API
uvicorn backend.main:app --reload

# 5. Start worker (separate terminal)
arq backend.worker.WorkerSettings
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
# Fill in VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, VITE_API_BASE_URL
npm run dev
```

### Docker (recommended)

```bash
cp .env.example .env
docker compose up --build
```

Runs the API, ARQ worker, and Valkey together. Nginx is configured separately on the host.

### Environment variables

| Variable | Where | Description |
|---|---|---|
| `SUPABASE_URL` | backend | Project URL from Supabase dashboard |
| `SUPABASE_ANON_KEY` | backend | Anon/public key |
| `SUPABASE_SERVICE_ROLE_KEY` | backend | Service role key (storage operations only) |
| `OPENAI_API_KEY` | backend | GPT-5 Mini access |
| `LLAMA_CLOUD_API_KEY` | backend | LlamaParse agentic tier |
| `VALKEY_URL` | backend | `redis://localhost:6379` by default |
| `VITE_SUPABASE_URL` | frontend | Same as backend |
| `VITE_SUPABASE_ANON_KEY` | frontend | Same as backend |
| `VITE_API_BASE_URL` | frontend | `http://localhost:8000` locally |

---

## Database schema

```
sessions          — one per study set, tracks current_question_index
questions         — 20 per session, position-ordered, answer key stored server-side only
answer_attempts   — one row per submission, idempotent on question_id
topic_stats       — ELO + p_known + attempts per topic per session
elo_history       — per-question ELO snapshots for full replay
chat_messages     — rolling window, last 10 turns served to LLM
generation_inputs — extracted PDF content + image refs
generation_images — stored image metadata, joined through generation_inputs
generation_topics — topics covered per generation round (for profile building)
```

Row-level security is enabled on all tables. The backend uses two Supabase clients: a per-request anon client (user JWT, RLS enforced) for all table queries, and a service role client for storage operations only. Write-heavy RPCs (`submit_answer`, `replace_questions_and_finalize`, `append_chat_turn`) are `SECURITY DEFINER` functions that verify session ownership before mutating anything, keeping the client role out of direct INSERT/DELETE on sensitive tables.

---

## Trade-offs and known limitations

**LLM grading is approximate.** FRQ scoring relies on GPT-5 Mini, which can be overgenerous with partial credit or miss nuanced errors. Confidence scores partially compensate but don't eliminate this. MCQ grading is deterministic and exact.

**No streaming.** Generation blocks until the model returns a full response. The async job queue eliminates gateway timeouts, but perceived latency during the polling wait is high (~90–130s for a full 20-question set with validation). Streaming tool use would improve this significantly.

**PDF size cap is 10 MB.** LlamaCloud's agentic parser is slow on large documents; the cap keeps p95 latency reasonable. Dense 200-page textbooks will hit content truncation at 12,000 chars.

**Image token budget is estimated.** Images exceeding `MAX_PROMPT_IMAGE_TOKENS` (20k tokens estimated) fall back to text descriptions. Token estimation uses a pixel-area heuristic, not an exact count.

**No spaced repetition scheduling.** The adaptive engine reweights question generation toward weak topics but does not implement a full SRS scheduler (SM-2, FSRS). `p_known` with a forgetting factor (`P_FORGET = 0.05`) is a lightweight proxy.

---

## Roadmap

**Spaced repetition scheduler** — replace the current per-session reweighting with a proper SM-2 or FSRS scheduler that reasons across sessions. The BKT `p_known` state and `elo_history` table already provide the signal; it's a matter of adding a scheduling layer on top. This is the single highest-leverage improvement: studykit becomes a long-term learning system rather than a per-session question generator.

**Embedding + retrieval layer** — embed source material with `text-embedding-3-small` and store vectors in Supabase `pgvector`. At generation time, retrieve the most relevant chunks per topic rather than fitting everything into one context window. This removes the 12,000-char truncation limit and makes generation grounded in retrieved evidence. The Supabase infrastructure is already in place.

**Misconception graph** — the answer validator already returns misconception signals per topic. Persisting these across sessions and using them to bias MCQ distractor generation would make the system genuinely personalised: wrong mental models get targeted specifically rather than just weak topics generally.

**Streaming generation** — stream validated questions back to the client as each one is approved rather than waiting for the full 20. Cuts perceived wait time significantly and allows the student to start answering while generation continues.

**Model distillation** — answer attempts with scores are labelled training data. Fine-tuning a smaller model on the FRQ grading task would make that component cheaper, faster, and independent of third-party model quality drift.

---

## Project structure

```
studykit/
├── README.md
├── pyproject.toml
├── docker-compose.yml
├── backend/
│   ├── main.py              # FastAPI app, lifespan, endpoints
│   ├── worker.py            # ARQ worker, task definitions, startup/shutdown
│   ├── processing.py        # QuestionGenerator, QuestionValidator,
│   │                        # AnswerValidator, StudyChatAssistant,
│   │                        # ImageFilter, TextFilter, ConceptExtractor,
│   │                        # AsyncPDFProcessor, DifficultyController
│   ├── session_store.py     # SessionStore — all Supabase table access
│   ├── storage.py           # StorageManager — PDF + image storage
│   ├── exceptions.py        # SessionNotFoundError, DatabaseError,
│   │                        # StorageError, RateLimitExceeded
│   ├── models.py            # Pydantic models, OpenAI tool schemas
│   ├── auth.py              # JWT verification
│   ├── config.py            # Pydantic Settings
│   ├── .env.example
│   └── supabase/
│       └── migrations/      # SQL migrations, RLS policies, RPC functions
└── frontend/
    ├── src/
    │   ├── pages/
    │   │   ├── Dashboard.jsx
    │   │   └── StudyPage.jsx
    │   ├── components/
    │   │   └── MarkdownMessage.jsx  # Markdown + KaTeX + Mermaid renderer
    │   ├── context/
    │   │   ├── AuthContext.jsx
    │   │   ├── ThemeContext.jsx
    │   │   └── ToastContext.jsx
    │   └── utils/
    │       └── api.js
    ├── vercel.json
    ├── package.json
    └── .env.example
```