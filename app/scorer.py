from typing import Dict, List, Tuple
from rich.console import Console
from rich.table import Table
from rich import print as rprint

console = Console()

OPTION_KEYS = ["A", "B", "C", "D"]


def get_option_text(question: Dict, option: str) -> str:
    """Return the text of option A/B/C/D for a question dict."""
    return question[f"option_{option.lower()}"]


def score_session(
    questions: List[Dict],
    user_answers: List[str],
) -> Tuple[int, int, List[Dict]]:
    correct_count = 0
    results = []

    for q, chosen in zip(questions, user_answers):
        chosen = chosen.upper().strip()
        correct = q["correct_option"].upper()
        is_correct = chosen == correct

        if is_correct:
            correct_count += 1

        results.append(
            {
                "question_id": q.get("id"),
                "question_text": q["question_text"],
                "chosen_option": chosen,
                "chosen_text": get_option_text(q, chosen) if chosen in OPTION_KEYS else "?",
                "correct_option": correct,
                "correct_text": get_option_text(q, correct),
                "is_correct": is_correct,
                "explanation": q.get("explanation", ""),
                "topic_tag": q.get("topic_tag", ""),
                "section_id": q.get("section_id"),
            }
        )

    return correct_count, len(questions), results


def display_results(results: List[Dict], correct: int, total: int) -> None:
    """Pretty-print session results to the terminal using Rich."""
    console.rule("[bold blue]Session Results")

    for i, r in enumerate(results, 1):
        icon = "[green]✓[/green]" if r["is_correct"] else "[red]✗[/red]"
        console.print(f"\n[bold]Q{i}.[/bold] {icon}  {r['question_text']}")

        if not r["is_correct"]:
            console.print(
                f"  [red]Your answer :[/red] ({r['chosen_option']}) {r['chosen_text']}"
            )
            console.print(
                f"  [green]Correct     :[/green] ({r['correct_option']}) {r['correct_text']}"
            )
            console.print(
                f"  [yellow]Explanation :[/yellow] {r['explanation']}"
            )
        else:
            console.print(
                f"  [green]Correct :[/green] ({r['correct_option']}) {r['correct_text']}"
            )

    pct = round(correct / total * 100, 1) if total else 0
    colour = "green" if pct >= 70 else "yellow" if pct >= 50 else "red"
    console.rule()
    console.print(
        f"\n[bold {colour}]Score: {correct}/{total}  ({pct}%)[/bold {colour}]\n"
    )
