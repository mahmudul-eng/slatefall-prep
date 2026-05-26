import json
import os
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

from app import knowledge_base as kb
from app.knowledge_base import DB_PATH, get_kb_snapshot
from app.pdf_parser import list_sections, PDF_PATH
from app.session import run_prep_session, run_simulated_session

app = typer.Typer(
    name="slatefall-prep",
    help="Adaptive Document Preparation System — SLATEFALL Dossier",
    add_completion=False,
)
console = Console()

from app.pdf_parser import PDF_PATH


# Commands


@app.command()
def sections():
    """List all available sections in the SLATEFALL dossier."""
    available = list_sections(PDF_PATH)
    table = Table(title="Available Sections", show_lines=True)
    table.add_column("ID", style="cyan", width=4)
    table.add_column("Title", style="white")
    for sid, title in available.items():
        table.add_row(str(sid), title)
    console.print(table)


@app.command()
def prep(
    sections_arg: str = typer.Option(
        ..., "--sections", "-s",
        help="Comma-separated section IDs to study, e.g. '3,7'"
    ),
    n: int = typer.Option(5, "--n", help="Questions per section (default 5)"),
):
    """
    Run an interactive prep session for the given sections.
    Automatically adapts to your history if you've studied these sections before.
    """
    try:
        section_ids = [int(x.strip()) for x in sections_arg.split(",")]
    except ValueError:
        console.print("[red]Invalid section IDs. Use comma-separated integers, e.g. '3,7'[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Starting prep session for sections: {section_ids}[/bold]")
    session_id, summary = run_prep_session(
        section_ids=section_ids,
        n_per_section=n,
    )
    console.print(f"\n[dim]Session complete. Session ID: {session_id}[/dim]")


@app.command()
def snapshot(
    top: int = typer.Option(5, "--top", help="Number of recent sessions to show"),
):
    """Show a KB snapshot: the last N sessions with question-level detail."""
    kb.init_db(DB_PATH)
    snap = get_kb_snapshot(DB_PATH, top_n=top)

    if not snap["sessions"]:
        console.print("[yellow]No sessions in the KB yet. Run a prep session first.[/yellow]")
        return

    for sess in snap["sessions"]:
        console.rule(
            f"[bold]Session {sess['id']} | "
            f"Sections {sess['section_ids']} | "
            f"{'Adaptive' if sess['is_adaptive'] else 'Cold-start'} | "
            f"Score: {sess['score']} ({sess['score_pct']}%)[/bold]"
        )
        console.print(f"  [dim]Created: {sess['created_at']}[/dim]")

        table = Table(show_header=True, header_style="bold magenta", show_lines=False)
        table.add_column("Q#", width=3)
        table.add_column("Section", width=7)
        table.add_column("Topic", width=22)
        table.add_column("Answer", width=8)
        table.add_column("Correct", width=8)
        table.add_column("✓/✗", width=4)

        for i, q in enumerate(sess["questions"], 1):
            icon = "[green]✓[/green]" if q["is_correct"] else "[red]✗[/red]"
            table.add_row(
                str(i),
                str(q["section_id"]),
                (q["topic_tag"] or "—")[:22],
                q["user_answer"] or "—",
                q["correct_option"],
                icon,
            )
        console.print(table)


@app.command(name="scenario-a")
def scenario_a(
    sections_arg: str = typer.Option(
        "1,4", "--sections", "-s",
        help="Sections for cold-start Scenario A (default: 1,4)"
    ),
    n: int = typer.Option(5, "--n", help="Questions per section"),
):
    """
    Scenario A: cold-start prep over any two sections (simulated answers).
    Saves output to outputs/scenario_a/.
    """
    try:
        section_ids = [int(x.strip()) for x in sections_arg.split(",")]
    except ValueError:
        console.print("[red]Invalid section IDs.[/red]")
        raise typer.Exit(1)

    out_dir = Path("outputs/scenario_a")
    out_dir.mkdir(parents=True, exist_ok=True)

    console.rule("[bold blue]Scenario A — Cold-Start Run")
    session_id, summary, results = run_simulated_session(
        section_ids=section_ids,
        correct_rate=0.6,
        n_per_section=n,
    )

    # Build questions output
    questions_out = []
    snap = get_kb_snapshot(DB_PATH, top_n=1)
    if snap["sessions"]:
        sess = snap["sessions"][0]
        for q in sess["questions"]:
            questions_out.append({
                "question_id": q["question_id"],
                "section_id": q["section_id"],
                "topic_tag": q["topic_tag"],
                "question_text": q["question_text"],
                "options": q["options"],
                "correct_option": q["correct_option"],
                "user_answer": q["user_answer"],
                "is_correct": q["is_correct"],
                "explanation": q["explanation"],
            })

    (out_dir / "questions_scenario_a.json").write_text(
        json.dumps({"session_summary": summary, "questions": questions_out}, indent=2)
    )
    (out_dir / "kb_snapshot_scenario_a.json").write_text(
        json.dumps(get_kb_snapshot(DB_PATH, top_n=5), indent=2)
    )

    console.print(f"\n[green]✓ Scenario A outputs saved to {out_dir}/[/green]")


@app.command(name="scenario-b")
def scenario_b(
    n: int = typer.Option(5, "--n", help="Questions per section (default 5)"),
):
    """
    Scenario B: three consecutive iterations as required by the assessment.
      Iter 1 : sections 5, 8
      Iter 2 : sections 6, 8, 9
      Iter 3 : section 8
    Outputs saved to outputs/scenario_b_iter{1,2,3}/.
    """
    from scenario_runner import run_scenario_b
    run_scenario_b(n_per_section=n)


# Entry point

if __name__ == "__main__":
    app()
