import json
import random
from pathlib import Path
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from rich.console import Console
from rich.rule import Rule

load_dotenv()

from app import knowledge_base as kb
from app.knowledge_base import DB_PATH, get_kb_snapshot
from app.llm_client import generate_mcqs
from app.pdf_parser import get_sections, SECTION_TITLES
from app.scorer import score_session
from app.session import run_simulated_session

console = Console()

SCENARIO_B = [
    {"iter": 1, "sections": [5, 8],    "seed": 1, "correct_rate": 0.60},
    {"iter": 2, "sections": [6, 8, 9], "seed": 2, "correct_rate": 0.55},
    {"iter": 3, "sections": [8],       "seed": 3, "correct_rate": 0.65},
]

OUTPUT_ROOT = Path("outputs")


def _questions_to_output(session_id: int, results: List[Dict], summary: Dict) -> Dict:
    """
    Build the questions_iter{N}.json payload.
    Includes session metadata, adaptive context used, and per-question answer detail.
    """
    questions_detail = []
    for r in results:
        questions_detail.append({
            "section_id":     r["section_id"],
            "topic_tag":      r.get("topic_tag", ""),
            "question_text":  r["question_text"],
            "options": {
                "A": r.get("option_a") or r.get("chosen_text", ""),  # fallback
                "B": "",  # populated below from KB
                "C": "",
                "D": "",
            },
            "correct_option": r["correct_option"],
            "correct_text":   r["correct_text"],
            "user_answer":    r["chosen_option"],
            "user_answer_text": r["chosen_text"],
            "is_correct":     r["is_correct"],
            "explanation":    r["explanation"],
        })

    snap = get_kb_snapshot(DB_PATH, top_n=1)
    if snap["sessions"]:
        kb_questions = snap["sessions"][0]["questions"]
        for i, q in enumerate(kb_questions):
            if i < len(questions_detail):
                questions_detail[i]["options"] = q["options"]

    return {
        "session_summary": {
            "session_id":   summary["session_id"],
            "section_ids":  summary["section_ids"],
            "is_adaptive":  summary["is_adaptive"],
            "score":        f"{summary['correct']}/{summary['total']}",
            "score_pct":    summary["score_pct"],
        },
        "questions": questions_detail,
    }


def run_scenario_b(n_per_section: int = 5, db_path: Path = DB_PATH) -> None:
    """Run all three Scenario B iterations end-to-end."""
    kb.init_db(db_path)
    console.rule("[bold blue]Scenario B — Three Consecutive Adaptive Iterations", style="blue")

    for cfg in SCENARIO_B:
        iter_num  = cfg["iter"]
        sections  = cfg["sections"]
        seed      = cfg["seed"]
        c_rate    = cfg["correct_rate"]
        out_dir   = OUTPUT_ROOT / f"scenario_b_iter{iter_num}"
        out_dir.mkdir(parents=True, exist_ok=True)

        console.print(
            f"\n[bold yellow]━━━ Iteration {iter_num} "
            f"| Sections {sections} "
            f"| Correct rate ≈ {int(c_rate*100)}% ━━━[/bold yellow]"
        )

        prior = kb.get_sessions_for_sections(sections, db_path)
        is_adaptive = len(prior) > 0

        console.print(
            f"  Mode: [{'yellow]ADAPTIVE' if is_adaptive else 'green]COLD-START'}[/]"
        )
        if is_adaptive:
            weak = kb.get_weak_topics(sections, db_path)
            if weak:
                console.print("  [cyan]Top weak topics carried forward:[/cyan]")
                for w in weak[:4]:
                    console.print(
                        f"    • {w['topic_tag']} (wrong {w['wrong_count']}x, "
                        f"sec {w['section_id']})"
                    )

        sections_text = get_sections(
            Path(__file__).parent / "data" / "SLATEFALL_DOSSIER.pdf",
            sections
        )

        all_questions: List[Dict] = []
        for sid in sections:
            title = SECTION_TITLES.get(sid, f"Section {sid}")
            console.print(f"  Generating {n_per_section} Qs for §{sid}: {title} …")

            weak_topics  = kb.get_weak_topics([sid], db_path)  if is_adaptive else None
            mastered     = kb.get_mastered_questions([sid], db_path) if is_adaptive else None

            qs = generate_mcqs(
                section_id=sid,
                section_title=title,
                section_text=sections_text[sid],
                n_questions=n_per_section,
                weak_topics=weak_topics,
                mastered_questions=mastered,
            )
            all_questions.extend(qs)

        random.seed(seed)
        options = ["A", "B", "C", "D"]
        user_answers: List[str] = []
        for q in all_questions:
            correct = q["correct_option"].upper()
            if random.random() < c_rate:
                user_answers.append(correct)
            else:
                wrong = [o for o in options if o != correct]
                user_answers.append(random.choice(wrong))

        correct_count, total, results = score_session(all_questions, user_answers)

        session_id  = kb.create_session(sections, is_adaptive=is_adaptive, db_path=db_path)
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

        summary = {
            "session_id":  session_id,
            "section_ids": sections,
            "is_adaptive": is_adaptive,
            "correct":     correct_count,
            "total":       total,
            "score_pct":   round(correct_count / total * 100, 1) if total else 0,
        }

        console.print(
            f"  [green]✓[/green] Score: {correct_count}/{total} "
            f"({summary['score_pct']}%) | Session ID: {session_id}"
        )

        questions_payload = _questions_to_output(session_id, results, summary)
        snap = get_kb_snapshot(db_path, top_n=5)

        q_path   = out_dir / f"questions_iter{iter_num}.json"
        kb_path  = out_dir / f"kb_snapshot_iter{iter_num}.json"

        q_path.write_text(json.dumps(questions_payload, indent=2))
        kb_path.write_text(json.dumps(snap, indent=2))

        console.print(f"  [dim]Saved: {q_path}[/dim]")
        console.print(f"  [dim]Saved: {kb_path}[/dim]")

    console.rule("[bold green]Scenario B complete!", style="green")
    console.print(
        "\n[bold]Output files:[/bold]\n"
        "  outputs/scenario_b_iter1/questions_iter1.json\n"
        "  outputs/scenario_b_iter1/kb_snapshot_iter1.json\n"
        "  outputs/scenario_b_iter2/questions_iter2.json\n"
        "  outputs/scenario_b_iter2/kb_snapshot_iter2.json\n"
        "  outputs/scenario_b_iter3/questions_iter3.json\n"
        "  outputs/scenario_b_iter3/kb_snapshot_iter3.json\n"
    )


if __name__ == "__main__":
    run_scenario_b()
