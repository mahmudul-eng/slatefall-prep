import json
import os
import re
from typing import Dict, List, Optional

from groq import Groq

# Client setup

def _get_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY not set. Add it to your .env file or export it."
        )
    return Groq(api_key=api_key)


MODEL = "llama-3.3-70b-versatile"   # Best free Groq model for structured output


# Prompt builders

def _build_cold_start_prompt(
    section_id: int,
    section_title: str,
    section_text: str,
    n_questions: int,
) -> str:
    # Truncate to ~6000 chars to stay within context limits safely
    truncated = section_text[:6000]
    return f"""You are an expert quiz generator for a document study system.

Below is the full text of Section {section_id} ("{section_title}") from the SLATEFALL operational dossier.

Your task: Generate exactly {n_questions} multiple-choice questions (MCQs) that test detailed knowledge of this section.

Rules:
- Each question must have exactly 4 options: A, B, C, D
- Exactly one option must be correct
- Questions must be factual and grounded in the text below
- Include a short explanation (1-2 sentences) for why the correct answer is right
- Assign a short topic_tag (2-5 words) that categorises the concept being tested
- Vary difficulty: include 2 straightforward recall questions and {n_questions - 2} application/detail questions
- Do NOT repeat question stems from this list (if provided)

SECTION TEXT:
---
{truncated}
---

Respond ONLY with a valid JSON array. No preamble, no markdown fences. Format:
[
  {{
    "question_text": "...",
    "option_a": "...",
    "option_b": "...",
    "option_c": "...",
    "option_d": "...",
    "correct_option": "A",
    "explanation": "...",
    "topic_tag": "..."
  }},
  ...
]"""


def _build_adaptive_prompt(
    section_id: int,
    section_title: str,
    section_text: str,
    n_questions: int,
    weak_topics: List[Dict],
    mastered_questions: List[str],
) -> str:
    truncated = section_text[:6000]

    weak_summary = ""
    if weak_topics:
        lines = []
        for wt in weak_topics[:8]:  # top 8 weak areas
            lines.append(
                f"  - Topic: '{wt['topic_tag']}' "
                f"(wrong {wt['wrong_count']} time(s)) "
                f"— example question: \"{wt['last_question_text'][:80]}...\""
            )
        weak_summary = "WEAK AREAS (prioritise these topics):\n" + "\n".join(lines)
    else:
        weak_summary = "WEAK AREAS: None recorded yet."

    mastered_summary = ""
    if mastered_questions:
        sample = mastered_questions[:5]
        mastered_summary = (
            "MASTERED QUESTIONS (do NOT re-ask these or close variants):\n"
            + "\n".join(f"  - {q[:80]}" for q in sample)
        )
    else:
        mastered_summary = "MASTERED QUESTIONS: None yet."

    return f"""You are an adaptive quiz generator for a document study system.

The learner has previously studied Section {section_id} ("{section_title}") and has a performance history.

Your task: Generate exactly {n_questions} multiple-choice questions that:
1. FOCUS on the weak areas listed below (at least {max(1, n_questions // 2)} questions must target those topics)
2. AVOID repeating mastered questions or very similar variants
3. Introduce 1-2 new angles or details not covered by prior questions

{weak_summary}

{mastered_summary}

SECTION TEXT:
---
{truncated}
---

Rules:
- Each question: 4 options (A/B/C/D), exactly one correct
- Include explanation (1-2 sentences) and topic_tag (2-5 words)
- Vary question style: some recall, some inference, some "which of the following is NOT..."

Respond ONLY with a valid JSON array. No preamble, no markdown fences. Format:
[
  {{
    "question_text": "...",
    "option_a": "...",
    "option_b": "...",
    "option_c": "...",
    "option_d": "...",
    "correct_option": "A",
    "explanation": "...",
    "topic_tag": "..."
  }},
  ...
]"""


# MCQ generation

def _parse_mcq_response(raw: str, section_id: int) -> List[Dict]:
    """
    Parse the LLM JSON response into a list of question dicts.
    Strips markdown fences if the model ignores that instruction.
    """
    # Strip ```json ... ``` fences if present
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    try:
        questions = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"LLM returned invalid JSON for section {section_id}: {e}\n"
            f"Raw response (first 500 chars):\n{raw[:500]}"
        )

    if not isinstance(questions, list):
        raise ValueError(f"Expected a JSON array, got: {type(questions)}")

    normalised = []
    for i, q in enumerate(questions):
        required = [
            "question_text", "option_a", "option_b", "option_c", "option_d",
            "correct_option", "explanation",
        ]
        missing = [k for k in required if k not in q]
        if missing:
            raise ValueError(
                f"Question {i} in section {section_id} missing fields: {missing}"
            )
        q["section_id"] = section_id
        q["correct_option"] = q["correct_option"].upper().strip(".")
        q.setdefault("topic_tag", "general")
        q.setdefault("source_context", "")
        normalised.append(q)

    return normalised


def generate_mcqs(
    section_id: int,
    section_title: str,
    section_text: str,
    n_questions: int = 5,
    weak_topics: Optional[List[Dict]] = None,
    mastered_questions: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Generate MCQs for a section. Automatically switches to adaptive mode
    when weak_topics or mastered_questions are provided.
    """
    client = _get_client()
    is_adaptive = bool(weak_topics or mastered_questions)

    if is_adaptive:
        prompt = _build_adaptive_prompt(
            section_id, section_title, section_text, n_questions,
            weak_topics or [], mastered_questions or [],
        )
    else:
        prompt = _build_cold_start_prompt(
            section_id, section_title, section_text, n_questions
        )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=3000,
    )

    raw = response.choices[0].message.content
    questions = _parse_mcq_response(raw, section_id)

    # Ensure we return exactly n_questions (trim if LLM over-generates)
    return questions[:n_questions]


def generate_clarification(
    question_text: str,
    correct_option: str,
    correct_text: str,
    chosen_text: str,
    section_context: str,
) -> str:
    """
    Generate a concise clarification for a wrong answer.
    Called per wrong answer during scoring.
    """
    client = _get_client()
    prompt = f"""A student answered a quiz question incorrectly.

Question: {question_text}
Student chose: "{chosen_text}"
Correct answer: "{correct_text}"

Relevant context:
{section_context[:800]}

Write a concise clarification (2-3 sentences) explaining why the correct answer is right
and why the student's choice was wrong. Be specific and educational.
Respond with plain text only."""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=200,
    )
    return response.choices[0].message.content.strip()
