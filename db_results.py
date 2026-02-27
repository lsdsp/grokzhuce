import asyncio
import time
from typing import Any, Dict

# 内存数据库，用于临时存储验证码结果
results_db: Dict[str, Dict[str, Any]] = {}
results_lock = asyncio.Lock()


async def init_db():
    print("[系统] 结果数据库初始化成功 (内存模式)")


async def save_result(task_id, task_type, data):
    # 保留 createTime 等已有字段，避免后续状态覆盖导致清理失效。
    now = int(time.time())
    new_data = dict(data) if isinstance(data, dict) else {"value": data}

    async with results_lock:
        old_data = results_db.get(task_id, {})
        merged = dict(old_data)
        merged.update(new_data)
        if "value" in new_data:
            # value(包含成功 token 或 CAPTCHA_FAIL)落地后，清理旧的 NOT_READY 状态。
            merged.pop("status", None)
        merged.setdefault("createTime", old_data.get("createTime", now))
        merged["taskType"] = task_type
        merged["updatedTime"] = now
        results_db[task_id] = merged

    status = merged.get("value") or merged.get("status") or "正在处理"
    print(f"[系统] 任务 {task_id} 状态更新: {status}")


async def load_result(task_id):
    async with results_lock:
        result = results_db.get(task_id)
        return dict(result) if isinstance(result, dict) else result


async def cleanup_old_results(days_old=7):
    now = int(time.time())
    expire_seconds = max(1, int(days_old)) * 86400

    async with results_lock:
        to_delete = []
        for tid, res in results_db.items():
            created = None
            if isinstance(res, dict):
                created = res.get("createTime") or res.get("updatedTime")
            if isinstance(created, (int, float)) and now - int(created) > expire_seconds:
                to_delete.append(tid)

        for tid in to_delete:
            del results_db[tid]

    return len(to_delete)
