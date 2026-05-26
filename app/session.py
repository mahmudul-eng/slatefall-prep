import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rich.console import Console
from rich.prompt import Prompt

from app import knowledge_base as kb
from app.knowledge_base import DB_PATH
from app.llm_client import generate_mcqs
from app.pdf_parser import get_sections, SECTION_TITLES
from app.scorer import score_session, display_results

console = Console()

PDF_PATH = Path(__file__).parent.parent / "data" / "SLATEFALL_DOSSIER.pdf"
N_QUESTIONS_PER_SECTION = 5


# Core prep flow

def run_prep_session(
    section_ids: List[int],
    n_per_section: int = N_QUESTIONS_PER_SECTION,
    simulate_answers: Optional[List[str]] = None,  # None = interactive
    db_path: Path = DB_PATH,
) -> Tuple[int, Dict]:

    kb.init_db(db_path)

    # STEP 1: Check KB for prior history

    prior_sessions = kb.get_sessions_for_sections(section_ids, db_path)
    is_adaptive = len(prior_sessions) > 0

    if is_adaptive:
        console.print(
            f"\n[cyan]📚 Adaptive run detected.[/cyan] "
            f"Found {len(prior_sessions)} prior session(s) for these sections. "
            "Questions will focus on your weak areas.\n"
        )
    else:
        console.print(
            "\n[cyan]🆕 Cold-start run.[/cyan] No prior history for these sections.\n"
        )

    # STEP 2: Generate MCQs

    console.print("[bold]Fetching section text from PDF...[/bold]")
    sections_text = get_sections(PDF_PATH, section_ids)

    all_questions: List[Dict] = []
    for sid in section_ids:
        section_title = SECTION_TITLES.get(sid, f"Section {sid}")
        console.print(
            f"  Generating {n_per_section} questions for "
            f"Section {sid}: [italic]{section_title}[/italic] ..."
        )

        weak_topics = None
        mastered_questions = None

        if is_adaptive:
            weak_topics = kb.get_weak_topics([sid], db_path)
            mastered_questions = kb.get_mastered_questions([sid], db_path)

        questions = generate_mcqs(
            section_id=sid,
            section_title=section_title,
            section_text=sections_text[sid],
            n_questions=n_per_section,
            weak_topics=weak_topics if is_adaptive else None,
            mastered_questions=mastered_questions if is_adaptive else None,
        )
        all_questions.extend(questions)

    console.print(
        f"\n[green]✓[/green] Generated {len(all_questions)} questions total.\n"
    )

    # STEP 3: Present questions & collect answers

    user_answers: List[str] = []

    if simulate_answers is not None:
        # Automated / scenario mode
        user_answers = simulate_answers[:len(all_questions)]
        # Pad with correct answers if simulation list is short
        while len(user_answers) < len(all_questions):
            user_answers.append(all_questions[len(user_answers)]["correct_option"])
    else:
        console.rule("[bold blue]Prep Session — Answer the Questions")
        for i, q in enumerate(all_questions, 1):
            console.print(f"\n[bold]Q{i} (Section {q['section_id']}):[/bold] {q['question_text']}")
            console.print(f"  A) {q['option_a']}")
            console.print(f"  B) {q['option_b']}")
            console.print(f"  C) {q['option_c']}")
            console.print(f"  D) {q['option_d']}")

            while True:
                ans = Prompt.ask("  Your answer", choices=["A", "B", "C", "D"])
                if ans.upper() in ["A", "B", "C", "D"]:
                    user_answers.append(ans.upper())
                    break

    # STEP 4: Score the session

    correct, total, results = score_session(all_questions, user_answers)

    if simulate_answers is None:
        display_results(results, correct, total)

    # STEP 5: Persist to KB

    session_id = kb.create_session(section_ids, is_adaptive=is_adaptive, db_path=db_path)

    question_ids = kb.save_questions(session_id, all_questions, db_path)
    for q, qid in zip(all_questions, question_ids):
        q["id"] = qid

    for result in results:
        # result["question_id"] is still None until we map it
        q_idx = results.index(result)
        kb.save_answer(
            session_id=session_id,
            question_id=question_ids[q_idx],
            chosen_option=result["chosen_option"],
            is_correct=result["is_correct"],
            db_path=db_path,
        )

    score_summary = {
        "session_id": session_id,
        "section_ids": section_ids,
        "is_adaptive": is_adaptive,
        "correct": correct,
        "total": total,
        "score_pct": round(correct / total * 100, 1) if total else 0,
    }

    console.print(
        f"[dim]Session {session_id} saved to KB "
        f"({'adaptive' if is_adaptive else 'cold-start'}).[/dim]"
    )
    return session_id, score_summary


# Simulated answer generator (for Scenario B)

def _simulate_realistic_answers(
    questions: List[Dict],
    correct_rate: float = 0.6,
) -> List[str]:
    import random
    options = ["A", "B", "C", "D"]
    answers = []
    for q in questions:
        correct = q["correct_option"].upper()
        if random.random() < correct_rate:
            answers.append(correct)
        else:
            wrong_options = [o for o in options if o != correct]
            answers.append(random.choice(wrong_options))
    return answers


def run_simulated_session(
    section_ids: List[int],
    correct_rate: float = 0.6,
    n_per_section: int = N_QUESTIONS_PER_SECTION,
    db_path: Path = DB_PATH,
) -> Tuple[int, Dict, List[Dict]]:
    import random
    kb.init_db(db_path)

    prior_sessions = kb.get_sessions_for_sections(section_ids, db_path)
    is_adaptive = len(prior_sessions) > 0

    console.print(
        f"\n[bold cyan]Simulated Session[/bold cyan] — "
        f"Sections {section_ids} | "
        f"{'[yellow]ADAPTIVE[/yellow]' if is_adaptive else '[green]COLD START[/green]'}"
    )

    sections_text = get_sections(PDF_PATH, section_ids)
    all_questions: List[Dict] = []

    for sid in section_ids:
        section_title = SECTION_TITLES.get(sid, f"Section {sid}")
        console.print(f"  Generating questions for Section {sid}: {section_title} ...")

        weak_topics = kb.get_weak_topics([sid], db_path) if is_adaptive else None
        mastered = kb.get_mastered_questions([sid], db_path) if is_adaptive else None

        questions = generate_mcqs(
            section_id=sid,
            section_title=section_title,
            section_text=sections_text[sid],
            n_questions=n_per_section,
            weak_topics=weak_topics,
            mastered_questions=mastered,
        )
        all_questions.extend(questions)

    random.seed(42)  
    user_answers = _simulate_realistic_answers(all_questions, correct_rate)

    correct, total, results = score_session(all_questions, user_answers)

    # Persist
    session_id = kb.create_session(section_ids, is_adaptive=is_adaptive, db_path=db_path)
    question_ids = kb.save_questions(session_id, all_questions, db_path)
    for q, qid in zip(all_questions, question_ids):
        q["id"] = qid

    for i, result in enumerate(results):
        kb.save_answer(
            session_id=session_id,
            question_id=question_ids[i],
            chosen_option=result["chosen_option"],
            is_correct=result["is_correct"],
            db_path=db_path,
        )

    score_summary = {
        "session_id": session_id,
        "section_ids": section_ids,
        "is_adaptive": is_adaptive,
        "correct": correct,
        "total": total,
        "score_pct": round(correct / total * 100, 1) if total else 0,
    }

    console.print(
        f"  [green]✓[/green] Score: {correct}/{total} ({score_summary['score_pct']}%) "
        f"| Session ID: {session_id}"
    )

    return session_id, score_summary, results
