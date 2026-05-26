# Adaptive Document Preparation System
### SLATEFALL Dossier — AI/ML Intern Take-Home Assessment

---

## Overview

A CLI-driven backend system that ingests the SLATEFALL operational dossier (PDF), generates Multiple Choice Questions (MCQs) from selected sections using an LLM, scores user answers, and **adapts future question sets** based on historical weak areas.

The core adaptive intelligence: on any return run over a previously studied section, the system queries the Knowledge Base for topics that have been answered incorrectly across prior sessions and injects that history into the LLM prompt — biasing new question generation toward weak areas and deprioritising mastered content.

---

## Prerequisites

- Python 3.10+
- A free [Groq API key](https://console.groq.com) (no credit card required)

---

## Setup (under 5 minutes)

```bash
# 1. Clone the repo
git clone <your-repo-url>
cd slatefall-prep

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your Groq key
cp .env.example .env
# Edit .env and set: GROQ_API_KEY=your_key_here

# 4. Verify PDF is present
ls data/SLATEFALL_DOSSIER.pdf
```

---

## Running the Evaluation Scenarios

### Scenario B (primary — 3 adaptive iterations)
```bash
python main.py scenario-b
```
Outputs saved automatically to:
```
outputs/scenario_b_iter1/questions_iter1.json
outputs/scenario_b_iter1/kb_snapshot_iter1.json
outputs/scenario_b_iter2/questions_iter2.json
outputs/scenario_b_iter2/kb_snapshot_iter2.json
outputs/scenario_b_iter3/questions_iter3.json
outputs/scenario_b_iter3/kb_snapshot_iter3.json
```

### Scenario A (cold-start over any two sections)
```bash
python main.py scenario-a --sections 2,4
```

### Interactive prep session (human answers)
```bash
python main.py prep --sections 3,7
```

### List all available sections
```bash
python main.py sections
```

### View KB snapshot (last 5 sessions)
```bash
python main.py snapshot
```

---

## Architecture

```
slatefall-prep/
├── main.py               # Typer CLI — all user-facing commands
├── scenario_runner.py    # Automated Scenario B executor
├── app/
│   ├── pdf_parser.py     # PyMuPDF extraction + section splitting by heading
│   ├── knowledge_base.py # SQLite KB — sessions, questions, answers, adaptive queries
│   ├── llm_client.py     # Groq MCQ generation (cold-start + adaptive prompts)
│   ├── scorer.py         # Answer scoring + Rich terminal display
│   └── session.py        # Full prep flow orchestrator
├── data/
│   └── SLATEFALL_DOSSIER.pdf
├── outputs/              # Auto-generated scenario outputs
├── kb.sqlite             # Auto-created SQLite Knowledge Base
├── requirements.txt
└── .env                  # Your GROQ_API_KEY goes here
```

### Data Flow

```
PDF → pdf_parser (section extraction)
         ↓
   section_text + KB history (weak topics, mastered Qs)
         ↓
   llm_client (Groq MCQ generation — cold or adaptive prompt)
         ↓
   scorer (answer collection + scoring)
         ↓
   knowledge_base (persist session, questions, answers)
         ↓
   outputs/ (JSON files for evaluation)
```

---

## Knowledge Base Schema

**SQLite** with 4 tables:

| Table | Purpose |
|---|---|
| `sessions` | One row per prep run; stores section IDs, timestamp, adaptive flag |
| `session_sections` | Many-to-many: which sections were in each session |
| `questions` | All MCQs generated: text, options, correct answer, explanation, topic_tag |
| `answers` | Per-question user responses: chosen option, is_correct, timestamp |

### Key Query Patterns
- **Prior sessions for sections** → `session_sections` JOIN on section IDs
- **Weak topics** → `answers` WHERE `is_correct=0` GROUP BY `topic_tag`, ordered by frequency
- **Mastered questions** → questions with zero wrong answers across all attempts
- **KB snapshot** → top-N sessions with full question/answer detail (for output files)

---

## Adaptive Intelligence

The system distinguishes cold-start from adaptive runs:

**Cold-start** (no prior history for the requested sections):
- LLM receives section text + instruction to vary difficulty (2 recall + 3 detail questions)

**Adaptive** (prior sessions exist):
- KB is queried for:
  - `weak_topics`: topic_tags with the most wrong answers, per section
  - `mastered_questions`: questions answered correctly in all prior attempts
- Both are injected into the LLM prompt:
  - At least ⌈N/2⌉ questions must target weak topics
  - Mastered question stems are explicitly excluded
  - 1-2 new angles are requested to prevent stagnation

This means Iteration 3 (section 8 only) will carry forward weak-area data from **both** Iterations 1 and 2 (which both covered section 8), producing noticeably different and more targeted questions.

---

## Stack Choices & Justification

| Component | Choice | Reason |
|---|---|---|
| **Language** | Python 3.10+ | Dominant ML/data ecosystem; assessors expect it |
| **CLI** | Typer + Rich | Clean, typed CLI with beautiful terminal output; minimal boilerplate |
| **LLM** | Groq (llama-3.3-70b-versatile) | Free tier, fast inference, excellent instruction-following for JSON output |
| **PDF Parsing** | PyMuPDF (`fitz`) | Fastest Python PDF library; deterministic text extraction on machine-readable PDFs |
| **Knowledge Base** | SQLite | Zero-setup, file-based, fully queryable with standard SQL; perfect for local evaluation |
| **Orchestration** | Raw API calls | No LangChain overhead; simpler debugging; full prompt control for adaptive logic |
| **No vector store** | — | The dossier is structured with named sections; keyword/tag-based weak-area tracking is simpler and more interpretable than embedding similarity for this use case |

---

## Known Limitations & Assumptions

1. **Section numbering**: The dossier uses "Section N." headings which map directly to IDs 1–10. No remapping needed.
2. **LLM non-determinism**: MCQ content varies between runs due to temperature=0.7. Structural correctness (4 options, one answer, explanation) is enforced by parsing validation.
3. **Context truncation**: Section text is truncated at 6,000 characters for the LLM prompt to stay within Groq's context window safely. All 10 sections fit comfortably within this limit.
4. **Simulated answers**: Scenario B uses seeded random simulation (~60% correct) to demonstrate adaptive behavior reproducibly. Seeds are fixed per iteration (1, 2, 3).
5. **No concurrent session handling**: SQLite WAL mode is enabled but the system is designed for single-user sequential use.
6. **Groq rate limits**: The free tier allows ~30 requests/minute. Scenario B makes 8 LLM calls total and stays well within this.

---

## Evaluation Scenario B — What to Expect

| Iteration | Sections | Mode | Expected behavior |
|---|---|---|---|
| 1 | 5, 8 | Cold-start | Fresh questions on Tactics (§5) and Bases (§8) |
| 2 | 6, 8, 9 | Adaptive for §8 | §8 questions focus on weak areas from Iter 1; §6, §9 are cold-start |
| 3 | 8 | Adaptive | §8 questions heavily weighted toward topics wrong in both Iters 1 & 2 |

The `is_adaptive` flag in each `kb_snapshot_iterN.json` and the `weak_topics` logged in console output confirm that adaptive prompting is grounded in real KB data.
