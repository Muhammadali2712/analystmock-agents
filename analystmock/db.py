import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from analystmock.models import Feedback, Quiz


@dataclass
class Session:
    id: int
    user_id: int
    label: str
    quiz: Quiz
    position: int
    awaiting_next: bool
    status: str

    @property
    def question(self):
        return self.quiz.questions[self.position]


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS dialogs (
                user_id INTEGER PRIMARY KEY,
                awaiting_vacancy INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                quiz TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                awaiting_next INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_session
                ON sessions(user_id) WHERE status = 'active';
            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                answer TEXT NOT NULL,
                feedback TEXT NOT NULL,
                score INTEGER NOT NULL,
                uncertain INTEGER NOT NULL,
                flagged INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_id, position),
                UNIQUE(user_id, message_id)
            );
            CREATE TABLE IF NOT EXISTS requests (
                user_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                count INTEGER NOT NULL,
                PRIMARY KEY(user_id, day)
            );
        """)

    def close(self) -> None:
        self.connection.close()

    def reserve_request(self, user_id: int, limit: int) -> bool:
        day = datetime.now(timezone.utc).date().isoformat()
        with self.connection:
            cursor = self.connection.execute(
                """INSERT INTO requests(user_id, day, count) VALUES (?, ?, 1)
                   ON CONFLICT(user_id, day) DO UPDATE SET count = count + 1
                   WHERE count < ?""",
                (user_id, day, limit),
            )
        return cursor.rowcount == 1

    def waiting_for_vacancy(self, user_id: int) -> bool:
        row = self.connection.execute(
            "SELECT awaiting_vacancy FROM dialogs WHERE user_id = ?", (user_id,)
        ).fetchone()
        return bool(row and row[0])

    def set_vacancy_mode(self, user_id: int, value: bool) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO dialogs(user_id, awaiting_vacancy) VALUES (?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET awaiting_vacancy = excluded.awaiting_vacancy""",
                (user_id, int(value)),
            )

    def _session(self, row) -> Session | None:
        if row is None:
            return None
        return Session(
            id=row["id"], user_id=row["user_id"], label=row["label"],
            quiz=Quiz.model_validate_json(row["quiz"]), position=row["position"],
            awaiting_next=bool(row["awaiting_next"]), status=row["status"],
        )

    def active(self, user_id: int) -> Session | None:
        return self._session(self.connection.execute(
            "SELECT * FROM sessions WHERE user_id = ? AND status = 'active'", (user_id,)
        ).fetchone())

    def create(self, user_id: int, label: str, quiz: Quiz) -> Session:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO sessions(user_id, label, quiz) VALUES (?, ?, ?)",
                (user_id, label, quiz.model_dump_json()),
            )
            self.connection.execute("DELETE FROM dialogs WHERE user_id = ?", (user_id,))
        return Session(cursor.lastrowid, user_id, label, quiz, 0, False, "active")

    def cancel(self, user_id: int) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE sessions SET status = 'cancelled' WHERE user_id = ? AND status = 'active'",
                (user_id,),
            )
            self.connection.execute("DELETE FROM dialogs WHERE user_id = ?", (user_id,))

    def processed(self, user_id: int, message_id: int) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM answers WHERE user_id = ? AND message_id = ?", (user_id, message_id)
        ).fetchone() is not None

    def save_answer(self, session: Session, message_id: int, answer: str, feedback: Feedback) -> None:
        finished = session.position == len(session.quiz.questions) - 1
        with self.connection:
            self.connection.execute(
                """INSERT INTO answers
                   (session_id, user_id, position, message_id, topic, answer, feedback, score, uncertain)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session.id, session.user_id, session.position, message_id, session.question.topic,
                 answer, feedback.model_dump_json(), feedback.score, int(feedback.uncertain)),
            )
            self.connection.execute(
                "UPDATE sessions SET awaiting_next = 1, status = ? WHERE id = ? AND user_id = ?",
                ("completed" if finished else "active", session.id, session.user_id),
            )

    def next_question(self, user_id: int) -> Session | None:
        with self.connection:
            self.connection.execute(
                """UPDATE sessions SET position = position + 1, awaiting_next = 0
                   WHERE user_id = ? AND status = 'active' AND awaiting_next = 1""",
                (user_id,),
            )
        return self.active(user_id)

    def latest_feedback(self, user_id: int) -> Feedback | None:
        row = self.connection.execute(
            "SELECT feedback FROM answers WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
        return Feedback.model_validate_json(row[0]) if row else None

    def flag_latest(self, user_id: int) -> bool:
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE answers SET flagged = 1 WHERE id =
                   (SELECT id FROM answers WHERE user_id = ? ORDER BY id DESC LIMIT 1)""",
                (user_id,),
            )
        return cursor.rowcount == 1

    def recent_questions(self, user_id: int) -> list[str]:
        rows = self.connection.execute(
            "SELECT quiz FROM sessions WHERE user_id = ? ORDER BY id DESC LIMIT 3", (user_id,)
        ).fetchall()
        return [question.prompt for row in rows for question in Quiz.model_validate_json(row[0]).questions]

    def history(self, user_id: int) -> list[dict]:
        rows = self.connection.execute(
            """SELECT s.id, s.label, s.status, s.created_at, COUNT(a.id) AS answered,
                      AVG(CASE WHEN a.uncertain = 0 AND a.flagged = 0 THEN a.score END) AS average
               FROM sessions s LEFT JOIN answers a ON a.session_id = s.id
               WHERE s.user_id = ? GROUP BY s.id ORDER BY s.id DESC LIMIT 5""",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def statistics(self, user_id: int) -> dict:
        counts = self.connection.execute(
            """SELECT COUNT(*) AS answers, COALESCE(SUM(uncertain), 0) AS uncertain,
                      COALESCE(SUM(flagged), 0) AS flagged
               FROM answers WHERE user_id = ?""", (user_id,)
        ).fetchone()
        completed = self.connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id = ? AND status = 'completed'", (user_id,)
        ).fetchone()[0]
        topics = self.connection.execute(
            """SELECT topic, COUNT(*) AS count, AVG(score) AS average FROM answers
               WHERE user_id = ? AND uncertain = 0 AND flagged = 0
               GROUP BY topic ORDER BY average ASC""", (user_id,)
        ).fetchall()
        scores = self.connection.execute(
            """SELECT score FROM answers WHERE user_id = ? AND uncertain = 0 AND flagged = 0
               ORDER BY id DESC LIMIT 10""", (user_id,)
        ).fetchall()
        return {**dict(counts), "completed": completed,
                "topics": [dict(row) for row in topics], "scores": [row[0] for row in scores]}
