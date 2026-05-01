import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager

DB_PATH = "dsa_revisions.db"

# Spaced repetition intervals in days
INTERVALS = [1, 2, 7, 30]


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                chat_id      INTEGER NOT NULL,
                title        TEXT NOT NULL,
                notes        TEXT DEFAULT '',
                category     TEXT DEFAULT 'General',
                added_date   TEXT NOT NULL,
                review_count INTEGER DEFAULT 0,
                next_review  TEXT NOT NULL,
                last_reminded TEXT,
                is_active    INTEGER DEFAULT 1
            )
        """)


def next_review_date(review_count: int) -> str:
    interval = INTERVALS[min(review_count, len(INTERVALS) - 1)]
    return (datetime.now() + timedelta(days=interval)).strftime("%Y-%m-%d %H:%M")


def add_question(user_id: int, chat_id: int, title: str, notes: str, category: str) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO questions (user_id, chat_id, title, notes, category, added_date, next_review) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, title, notes, category, now, next_review_date(0)),
        )
        return cur.lastrowid


def get_question(question_id: int):
    with get_db() as conn:
        return conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()


def get_user_questions(user_id: int):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM questions WHERE user_id = ? AND is_active = 1 ORDER BY next_review",
            (user_id,),
        ).fetchall()


def get_due_questions(now_str: str, reminded_before: str):
    """Questions due for review that haven't been reminded recently (within 4h)."""
    with get_db() as conn:
        return conn.execute(
            """SELECT * FROM questions
               WHERE is_active = 1
               AND next_review <= ?
               AND (last_reminded IS NULL OR last_reminded <= ?)
               ORDER BY next_review""",
            (now_str, reminded_before),
        ).fetchall()


def get_due_for_user(user_id: int, now_str: str):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM questions WHERE user_id = ? AND is_active = 1 AND next_review <= ? ORDER BY next_review",
            (user_id, now_str),
        ).fetchall()


def mark_reviewed(question_id: int) -> dict:
    with get_db() as conn:
        q = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
        if not q:
            return {}
        new_count = q["review_count"] + 1
        conn.execute(
            "UPDATE questions SET review_count = ?, next_review = ?, last_reminded = NULL WHERE id = ?",
            (new_count, next_review_date(new_count), question_id),
        )
        return dict(q) | {"review_count": new_count}


def snooze_question(question_id: int, until: datetime):
    with get_db() as conn:
        conn.execute(
            "UPDATE questions SET next_review = ?, last_reminded = ? WHERE id = ?",
            (until.strftime("%Y-%m-%d %H:%M"), datetime.now().strftime("%Y-%m-%d %H:%M"), question_id),
        )


def update_last_reminded(question_id: int):
    with get_db() as conn:
        conn.execute(
            "UPDATE questions SET last_reminded = ? WHERE id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M"), question_id),
        )


def delete_question(question_id: int, user_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE questions SET is_active = 0 WHERE id = ? AND user_id = ?",
            (question_id, user_id),
        )
        return cur.rowcount > 0


def get_stats(user_id: int) -> dict:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM questions WHERE user_id = ? AND is_active = 1", (user_id,)
        ).fetchone()[0]
        mastered = conn.execute(
            "SELECT COUNT(*) FROM questions WHERE user_id = ? AND is_active = 1 AND review_count >= ?",
            (user_id, len(INTERVALS)),
        ).fetchone()[0]
        total_reviews = conn.execute(
            "SELECT COALESCE(SUM(review_count), 0) FROM questions WHERE user_id = ? AND is_active = 1",
            (user_id,),
        ).fetchone()[0]
        due_now = conn.execute(
            "SELECT COUNT(*) FROM questions WHERE user_id = ? AND is_active = 1 AND next_review <= ?",
            (user_id, now_str),
        ).fetchone()[0]
    return {"total": total, "mastered": mastered, "total_reviews": total_reviews, "due_now": due_now}
