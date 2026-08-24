import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class MemoryStore:
    """SQLite tabanlı kalıcı hafıza: conversations + memories."""

    def __init__(self, config: dict):
        mem_cfg = (config.get("memory", {}) or {})
        self.enabled = bool(mem_cfg.get("enabled", True))
        self.session_id = str(mem_cfg.get("session_id", "default"))
        db_path = str(mem_cfg.get("db_path", "data/elisha.db"))
        root = Path(__file__).resolve().parent.parent
        self.db_path = Path(db_path)
        if not self.db_path.is_absolute():
            self.db_path = root / self.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            c = self._conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                category TEXT DEFAULT 'genel',
                importance REAL DEFAULT 1.0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id, id)")
            self._conn.commit()

    # ---------- conversations ----------

    def save_message(self, role: str, content: str,
                     session_id: Optional[str] = None):
        if not self.enabled:
            return
        sid = session_id or self.session_id
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (sid, role, content[:4000], time.time()))
            self._conn.commit()

    def recent_messages(self, limit: int = 10,
                        session_id: Optional[str] = None) -> List[Dict[str, str]]:
        sid = session_id or self.session_id
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM conversations WHERE session_id = ? "
                "ORDER BY id DESC LIMIT ?", (sid, int(limit))).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def clear_conversations(self, session_id: Optional[str] = None) -> int:
        """Oturum konuşma geçmişini sıfırla (uzun süreli anılar KORUNUR).
        Bozuk/halüsinasyon içeren geçmişi temizlemek için."""
        sid = session_id or self.session_id
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM conversations WHERE session_id = ?", (sid,))
            self._conn.commit()
            return cur.rowcount

    # ---------- memories ----------

    def remember(self, key: str, value: str, category: str = "genel",
                 importance: float = 1.0) -> bool:
        if not key or not value:
            return False
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO memories (key, value, category, importance, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                     category=excluded.category, importance=excluded.importance,
                     updated_at=excluded.updated_at""",
                (key.strip().lower(), value.strip(), category or "genel",
                 float(importance), now, now))
            self._conn.commit()
        return True

    def recall(self, query: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            if not query:
                rows = self._conn.execute(
                    "SELECT * FROM memories ORDER BY importance DESC, updated_at DESC LIMIT ?",
                    (int(limit),)).fetchall()
            else:
                words = [w for w in re.split(r"\W+", query.lower()) if len(w) > 2]
                rows = self._conn.execute(
                    "SELECT * FROM memories ORDER BY importance DESC, updated_at DESC LIMIT 200"
                ).fetchall()
            out = []
            for r in rows:
                item = dict(r)
                if query and words:
                    hay = f"{r['key']} {r['value']} {r['category']}".lower()
                    score = sum(1 for w in words if w in hay)
                    if score == 0:
                        continue
                    item["_score"] = score
                else:
                    item["_score"] = 0
                out.append(item)
            if query and words:
                out.sort(key=lambda x: (-x["_score"], -x["importance"]))
            return out[: int(limit)]

    def forget(self, key_or_text: str) -> int:
        k = (key_or_text or "").strip().lower()
        if not k:
            return 0
        with self._lock:
            cur = self._conn.execute("DELETE FROM memories WHERE key = ?", (k,))
            deleted = cur.rowcount
            if deleted == 0:
                like = f"%{k}%"
                cur = self._conn.execute(
                    "DELETE FROM memories WHERE key LIKE ? OR value LIKE ?", (like, like))
                deleted = cur.rowcount
            if deleted == 0:
                words = [w for w in re.split(r"\W+", k) if len(w) > 2]
                for w in words[:6]:
                    like = f"%{w}%"
                    cur = self._conn.execute(
                        "DELETE FROM memories WHERE key LIKE ? OR value LIKE ?", (like, like))
                    deleted += cur.rowcount
            self._conn.commit()
        return deleted

    def count_memories(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()
        return int(row["n"]) if row else 0

    def context_block(self, max_items: int = 12) -> str:
        """Sistem promptuna eklenecek kısa hafıza özeti."""
        items = self.recall("", limit=max_items)
        if not items:
            return ""
        lines = ["KULLANICI HAKKINDA HATIRADIKLARIN:"]
        for it in items:
            cat = it.get("category", "genel")
            lines.append(f"- ({cat}) {it['key']}: {it['value']}")
        return "\n".join(lines)

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
