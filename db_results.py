from solver_result_store import InMemorySolverResultStore, create_default_result_store


default_result_store = create_default_result_store()
results_db = default_result_store.results_db if isinstance(default_result_store, InMemorySolverResultStore) else {}
results_lock = default_result_store.results_lock if isinstance(default_result_store, InMemorySolverResultStore) else None


async def init_db():
    await default_result_store.init()


async def save_result(task_id, task_type, data):
    await default_result_store.save(task_id, task_type, data)


async def load_result(task_id):
    return await default_result_store.load(task_id)


async def cleanup_old_results(days_old=7):
    return await default_result_store.cleanup(days_old=days_old)
