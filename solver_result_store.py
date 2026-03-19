import asyncio
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional


class InMemorySolverResultStore:
    def __init__(self):
        self.results_db: Dict[str, Dict[str, Any]] = {}
        self.results_lock = asyncio.Lock()

    async def init(self):
        print("[系统] 结果数据库初始化成功 (内存模式)")

    async def save(self, task_id, task_type, data):
        now = int(time.time())
        new_data = dict(data) if isinstance(data, dict) else {"value": data}

        async with self.results_lock:
            old_data = self.results_db.get(task_id, {})
            merged = dict(old_data)
            merged.update(new_data)
            if "value" in new_data:
                merged.pop("status", None)
            merged.setdefault("createTime", old_data.get("createTime", now))
            merged["taskType"] = task_type
            merged["updatedTime"] = now
            self.results_db[task_id] = merged

        status = merged.get("value") or merged.get("status") or "正在处理"
        print(f"[系统] 任务 {task_id} 状态更新: {status}")

    async def load(self, task_id) -> Optional[Dict[str, Any]]:
        async with self.results_lock:
            result = self.results_db.get(task_id)
            return dict(result) if isinstance(result, dict) else result

    async def cleanup(self, days_old=7):
        now = int(time.time())
        expire_seconds = max(1, int(days_old)) * 86400

        async with self.results_lock:
            to_delete = []
            for tid, res in self.results_db.items():
                created = None
                if isinstance(res, dict):
                    created = res.get("createTime") or res.get("updatedTime")
                if isinstance(created, (int, float)) and now - int(created) > expire_seconds:
                    to_delete.append(tid)

            for tid in to_delete:
                del self.results_db[tid]

        return len(to_delete)


class SQLiteSolverResultStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = asyncio.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def _ensure_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            if self.db_path != ":memory:":
                Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _merge_result(self, existing: Optional[Dict[str, Any]], task_type: str, data) -> Dict[str, Any]:
        now = int(time.time())
        new_data = dict(data) if isinstance(data, dict) else {"value": data}
        merged = dict(existing or {})
        merged.update(new_data)
        if "value" in new_data:
            merged.pop("status", None)
        merged.setdefault("createTime", (existing or {}).get("createTime", now))
        merged["taskType"] = task_type
        merged["updatedTime"] = now
        return merged

    def _init_sync(self):
        conn = self._ensure_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS solver_results (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                create_time INTEGER NOT NULL,
                updated_time INTEGER NOT NULL,
                value TEXT,
                status TEXT,
                url TEXT,
                sitekey TEXT,
                action TEXT,
                cdata TEXT,
                elapsed_time REAL
            )
            """
        )
        conn.commit()

    async def init(self):
        async with self._lock:
            await asyncio.to_thread(self._init_sync)

    def _load_sync(self, task_id: str) -> Optional[Dict[str, Any]]:
        self._init_sync()
        conn = self._ensure_connection()
        row = conn.execute(
            """
            SELECT task_id, task_type, create_time, updated_time, value, status, url, sitekey, action, cdata, elapsed_time
            FROM solver_results
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        result = {
            "taskId": row["task_id"],
            "taskType": row["task_type"],
            "createTime": row["create_time"],
            "updatedTime": row["updated_time"],
        }
        for key in ("value", "status", "url", "sitekey", "action", "cdata", "elapsed_time"):
            value = row[key]
            if value is not None:
                result[key] = value
        return result

    async def load(self, task_id) -> Optional[Dict[str, Any]]:
        async with self._lock:
            return await asyncio.to_thread(self._load_sync, task_id)

    def _save_sync(self, task_id: str, task_type: str, data):
        self._init_sync()
        existing = self._load_sync(task_id)
        merged = self._merge_result(existing, task_type, data)
        conn = self._ensure_connection()
        conn.execute(
            """
            INSERT INTO solver_results (
                task_id, task_type, create_time, updated_time, value, status, url, sitekey, action, cdata, elapsed_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                task_type=excluded.task_type,
                create_time=excluded.create_time,
                updated_time=excluded.updated_time,
                value=excluded.value,
                status=excluded.status,
                url=excluded.url,
                sitekey=excluded.sitekey,
                action=excluded.action,
                cdata=excluded.cdata,
                elapsed_time=excluded.elapsed_time
            """,
            (
                task_id,
                merged["taskType"],
                merged["createTime"],
                merged["updatedTime"],
                merged.get("value"),
                merged.get("status"),
                merged.get("url"),
                merged.get("sitekey"),
                merged.get("action"),
                merged.get("cdata"),
                merged.get("elapsed_time"),
            ),
        )
        conn.commit()
        status = merged.get("value") or merged.get("status") or "正在处理"
        print(f"[系统] 任务 {task_id} 状态更新: {status}")

    async def save(self, task_id, task_type, data):
        async with self._lock:
            await asyncio.to_thread(self._save_sync, task_id, task_type, data)

    def _cleanup_sync(self, days_old=7):
        self._init_sync()
        now = int(time.time())
        expire_seconds = max(1, int(days_old)) * 86400
        threshold = now - expire_seconds
        conn = self._ensure_connection()
        cursor = conn.execute(
            "DELETE FROM solver_results WHERE COALESCE(create_time, updated_time, 0) < ?",
            (threshold,),
        )
        conn.commit()
        return cursor.rowcount

    async def cleanup(self, days_old=7):
        async with self._lock:
            return await asyncio.to_thread(self._cleanup_sync, days_old)


def create_default_result_store():
    store_kind = os.getenv("SOLVER_RESULT_STORE", "memory").strip().lower()
    if store_kind == "sqlite":
        db_path = os.getenv("SOLVER_RESULT_DB_PATH", "logs/solver/solver-results.sqlite3").strip() or "logs/solver/solver-results.sqlite3"
        return SQLiteSolverResultStore(db_path)
    return InMemorySolverResultStore()
