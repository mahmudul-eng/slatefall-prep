import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent.parent / "kb.sqlite"



# Connection helper


def _get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row  # dict-like rows
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Schema initialisation

DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,           -- ISO-8601 timestamp
    section_ids TEXT    NOT NULL,           -- JSON array of ints, e.g. "[5,8]"
    is_adaptive INTEGER NOT NULL DEFAULT 0  -- 0 = cold start, 1 = adaptive
);

CREATE TABLE IF NOT EXISTS session_sections (
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    section_id  INTEGER NOT NULL,
    PRIMARY KEY (session_id, section_id)
);

CREATE TABLE IF NOT EXISTS questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(id),
    section_id      INTEGER NOT NULL,
    question_text   TEXT    NOT NULL,
    option_a        TEXT    NOT NULL,
    option_b        TEXT    NOT NULL,
    option_c        TEXT    NOT NULL,
    option_d        TEXT    NOT NULL,
    correct_option  TEXT    NOT NULL,       -- 'A','B','C', or 'D'
    explanation     TEXT    NOT NULL,
    topic_tag       TEXT,                   -- optional keyword for adaptive grouping
    source_context  TEXT                    -- short excerpt that grounded the question
);

CREATE TABLE IF NOT EXISTS answers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(id),
    question_id     INTEGER NOT NULL REFERENCES questions(id),
    chosen_option   TEXT    NOT NULL,       -- 'A','B','C', or 'D'
    is_correct      INTEGER NOT NULL,       -- 1 or 0
    answered_at     TEXT    NOT NULL        -- ISO-8601 timestamp
);
"""


def init_db(db_path: Path = DB_PATH) -> None:
    """Create tables if they don't exist yet."""
    with _get_conn(db_path) as conn:
        conn.executescript(DDL)


# Session CRUD

def create_session(section_ids: List[int], is_adaptive: bool = False,
                   db_path: Path = DB_PATH) -> int:
    """Insert a new session row and its section links. Returns session_id."""
    now = datetime.utcnow().isoformat()
    with _get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO sessions (created_at, section_ids, is_adaptive) VALUES (?,?,?)",
            (now, json.dumps(sorted(section_ids)), int(is_adaptive)),
        )
        session_id = cur.lastrowid
        conn.executemany(
            "INSERT OR IGNORE INTO session_sections (session_id, section_id) VALUES (?,?)",
            [(session_id, sid) for sid in section_ids],
        )
    return session_id


def get_sessions_for_sections(section_ids: List[int],
                               db_path: Path = DB_PATH) -> List[Dict]:
    """
    Return all prior sessions that include AT LEAST ONE of the given section IDs.
    Used to decide whether a run is adaptive.
    """
    placeholders = ",".join("?" * len(section_ids))
    with _get_conn(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT s.*
            FROM sessions s
            JOIN session_sections ss ON ss.session_id = s.id
            WHERE ss.section_id IN ({placeholders})
            ORDER BY s.id ASC
            """,
            section_ids,
        ).fetchall()
    return [dict(r) for r in rows]


# Question CRUD

def save_questions(session_id: int, questions: List[Dict],
                   db_path: Path = DB_PATH) -> List[int]:
    """
    Persist a list of MCQ dicts for a session.
    Each dict must have keys: section_id, question_text, option_a..d,
    correct_option, explanation, topic_tag (optional), source_context (optional).
    Returns list of inserted question IDs.
    """
    ids = []
    with _get_conn(db_path) as conn:
        for q in questions:
            cur = conn.execute(
                """
                INSERT INTO questions
                  (session_id, section_id, question_text,
                   option_a, option_b, option_c, option_d,
                   correct_option, explanation, topic_tag, source_context)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    session_id,
                    q["section_id"],
                    q["question_text"],
                    q["option_a"],
                    q["option_b"],
                    q["option_c"],
                    q["option_d"],
                    q["correct_option"].upper(),
                    q["explanation"],
                    q.get("topic_tag", ""),
                    q.get("source_context", ""),
                ),
            )
            ids.append(cur.lastrowid)
    return ids


def get_questions_for_session(session_id: int,
                               db_path: Path = DB_PATH) -> List[Dict]:
    with _get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM questions WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# Answer CRUD

def save_answer(session_id: int, question_id: int, chosen_option: str,
                is_correct: bool, db_path: Path = DB_PATH) -> None:
    now = datetime.utcnow().isoformat()
    with _get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO answers (session_id, question_id, chosen_option,
                                 is_correct, answered_at)
            VALUES (?,?,?,?,?)
            """,
            (session_id, question_id, chosen_option.upper(),
             int(is_correct), now),
        )


def get_answers_for_session(session_id: int,
                             db_path: Path = DB_PATH) -> List[Dict]:
    with _get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM answers WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# Adaptive intelligence queries

def get_weak_topics(section_ids: List[int], db_path: Path = DB_PATH) -> List[Dict]:
    """
    Return topics/questions answered incorrectly across multiple prior sessions,
    filtered to the relevant section IDs.
    Returns list of dicts with keys: topic_tag, section_id, wrong_count,
    last_question_text — ordered by wrong_count DESC.
    """
    placeholders = ",".join("?" * len(section_ids))
    with _get_conn(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                q.topic_tag,
                q.section_id,
                COUNT(a.id)        AS wrong_count,
                MAX(q.question_text) AS last_question_text
            FROM answers a
            JOIN questions q ON q.id = a.question_id
            WHERE a.is_correct = 0
              AND q.section_id IN ({placeholders})
            GROUP BY q.topic_tag, q.section_id
            HAVING COUNT(DISTINCT a.session_id) >= 1
            ORDER BY wrong_count DESC
            """,
            section_ids,
        ).fetchall()
    return [dict(r) for r in rows]


def get_mastered_questions(section_ids: List[int],
                            db_path: Path = DB_PATH) -> List[str]:
    """
    Return question texts that have been answered correctly in ALL attempts
    across sessions for the given sections — these should be deprioritised.
    """
    placeholders = ",".join("?" * len(section_ids))
    with _get_conn(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT q.question_text
            FROM questions q
            JOIN answers a ON a.question_id = q.id
            WHERE q.section_id IN ({placeholders})
            GROUP BY q.question_text
            HAVING SUM(CASE WHEN a.is_correct = 0 THEN 1 ELSE 0 END) = 0
               AND COUNT(a.id) >= 1
            """,
            section_ids,
        ).fetchall()
    return [r["question_text"] for r in rows]


# KB Snapshot (for submission outputs)

def get_kb_snapshot(db_path: Path = DB_PATH, top_n: int = 5) -> Dict:
    """
    Human-readable export of the top-N most recent sessions with full detail:
    session metadata, questions asked, and answer results.
    Required by the assessment spec (Section 3.2).
    """
    with _get_conn(db_path) as conn:
        sessions = conn.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (top_n,)
        ).fetchall()

    snapshot = {"generated_at": datetime.utcnow().isoformat(), "sessions": []}

    for sess in sessions:
        sess_dict = dict(sess)
        sess_dict["section_ids"] = json.loads(sess_dict["section_ids"])

        questions = get_questions_for_session(sess_dict["id"], db_path)
        answers = get_answers_for_session(sess_dict["id"], db_path)
        answer_map = {a["question_id"]: a for a in answers}

        questions_detail = []
        for q in questions:
            ans = answer_map.get(q["id"])
            questions_detail.append(
                {
                    "question_id": q["id"],
                    "section_id": q["section_id"],
                    "topic_tag": q["topic_tag"],
                    "question_text": q["question_text"],
                    "options": {
                        "A": q["option_a"],
                        "B": q["option_b"],
                        "C": q["option_c"],
                        "D": q["option_d"],
                    },
                    "correct_option": q["correct_option"],
                    "user_answer": ans["chosen_option"] if ans else None,
                    "is_correct": bool(ans["is_correct"]) if ans else None,
                    "explanation": q["explanation"],
                }
            )

        correct = sum(1 for q in questions_detail if q["is_correct"])
        total = len(questions_detail)

        sess_dict["score"] = f"{correct}/{total}"
        sess_dict["score_pct"] = round(correct / total * 100, 1) if total else 0
        sess_dict["questions"] = questions_detail
        snapshot["sessions"].append(sess_dict)

    return snapshot
