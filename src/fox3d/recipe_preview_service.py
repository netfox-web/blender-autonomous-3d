"""Local, serial background rendering for the Recipe workbench."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock

from fox3d.ids import new_id
from fox3d.recipe_3d import (
    atomic_json, read_json, get_recipe_3d_dir, get_recipe_3d_status,
    generate_recipe_3d_product, input_hash,
)


class RecipePreviewService:
    def __init__(self, platform, *, folder_fn=get_recipe_3d_dir,
                 status_fn=get_recipe_3d_status, generate_fn=None):
        self.platform = platform
        self.folder_fn = folder_fn
        self.status_fn = status_fn
        self.generate_fn = generate_fn
        self.lock = RLock()
        self.tasks = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="recipe-preview")

    def status(self, tid, sku, draft):
        with self.lock:
            path = self.folder_fn(self.platform.root, tid, sku) / "state.json"
            state = read_json(path)
            if state.get("state") in {"queued", "running"} and (tid, sku) not in self.tasks:
                state.update(state="failed", error="工作台曾中斷，請重新生成；上一版成果仍保留。")
                atomic_json(path, state)
            return self.status_fn(self.platform.root, tid, sku, current_draft=draft)

    def submit(self, tid, sku, item):
        with self.lock:
            key = (tid, sku)
            if key in self.tasks:
                raise ValueError("此商品已有生成工作，請完成或取消後再試")
            task_id, stop = new_id(), Event()
            path = self.folder_fn(self.platform.root, tid, sku) / "state.json"
            state = {"taskId": task_id, "state": "queued", "progress": 0,
                     "inputHash": input_hash(item["draft"]), "error": None}
            if "batchVersion" in item["draft"]:
                state["batchVersion"] = item["draft"]["batchVersion"]
            atomic_json(path, state)
            self.tasks[key] = (task_id, stop)
            self.executor.submit(self._run, key, item, path, state, stop)
            return {"taskId": task_id, "state": "queued"}

    def _run(self, key, item, path, state, stop):
        try:
            if stop.is_set():
                return
            with self.lock:
                state.update(state="running", progress=10)
                atomic_json(path, state)
            def on_job(job):
                with self.lock:
                    state.update(jobId=job.get("jobId"), progress=25)
                    atomic_json(path, state)
            (self.generate_fn or generate_recipe_3d_product)(self.platform, *key, item["draft"], revision=item["revision"],
                                      generation_id=state["taskId"], on_job=on_job, cancel_flag=stop)
            state.update(state="succeeded", progress=100)
        except Exception as exc:
            state.update(state="failed", error=str(exc)[:1000])
        finally:
            with self.lock:
                if stop.is_set() and state["state"] != "succeeded":
                    state.update(state="cancelled", error=None)
                atomic_json(path, state)
                self.tasks.pop(key, None)

    def cancel(self, tid, sku, task_id):
        with self.lock:
            task = self.tasks.get((tid, sku))
            if task is None or task[0] != task_id:
                raise ValueError("此工作已結束，請重新整理狀態")
            task[1].set()
            return {"taskId": task_id, "cancelRequested": True}
