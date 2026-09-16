"""Local, serial background rendering for the Recipe workbench."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock
import logging
import re
import stat

from fox3d.ids import new_id
from fox3d.preview_ownership import PreviewOwnership, PreviewBusy
from fox3d.recipe_3d import (
    atomic_json, read_json, get_recipe_3d_dir, get_recipe_3d_status,
    generate_recipe_3d_product, input_hash, _ATOMIC_TEMP_TOKEN_LENGTH,
)


def _same_state_identity(current, expected):
    """Compare serialized identity types and optional-key presence without coercion."""
    if type(current) is not dict or type(expected) is not dict:
        return False
    for key in ('taskId', 'inputHash'):
        if (key not in current or key not in expected
                or type(current[key]) is not str or type(expected[key]) is not str
                or current[key] != expected[key]):
            return False
    if ('batchVersion' in current) != ('batchVersion' in expected):
        return False
    if 'batchVersion' in expected:
        return (type(current['batchVersion']) is int
                and type(expected['batchVersion']) is int
                and current['batchVersion'] == expected['batchVersion'])
    return True


def scavenge_state_temps(path, owner):
    """Remove only dead outer-state atomic debris under this workspace's guard.

    No content/mtime/PID is authority. Cooperating writers hold the same stable
    OS guard; unknown files and all nested trees are outside this cleanup scope.
    """
    if (not isinstance(owner, PreviewOwnership) or not owner.held or owner.stream.closed
            or path.name != 'state.json' or path.parent.resolve() != owner.folder):
        raise ValueError('清理前需取得同一商品工作區的生成鎖')
    # Match atomic_json's UUID-prefix naming contract, not a generic *.tmp glob.
    pattern = re.compile(re.escape(path.name) + rf'\.[0-9a-f]{{{_ATOMIC_TEMP_TOKEN_LENGTH}}}\.tmp')
    candidates = sorted((p for p in owner.folder.iterdir() if pattern.fullmatch(p.name)), key=lambda p: p.name)
    for candidate in candidates:
        details = candidate.lstat()
        if (candidate.parent != owner.folder or not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1
                or getattr(details, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
            raise ValueError('暫存檔型態無法確認，拒絕清理：' + candidate.name)
    removed = []
    for candidate in candidates:
        candidate.unlink()  # Any failure propagates before a new outer-state write.
        removed.append(candidate.name)
        logging.getLogger(__name__).info('Scavenged outer-state temp debris: %s', candidate.name)
    return removed


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
            if (tid, sku) not in self.tasks:
                try:
                    owner = PreviewOwnership(path.parent)
                except PreviewBusy:
                    pass  # Another process still owns it; a read must not fail it.
                else:
                    with owner:
                        scavenge_state_temps(path, owner)
                        state = read_json(path)
                        if state.get("state") in {"queued", "running"}:
                            state.update(state="failed", error="工作台曾中斷，請重新生成；上一版成果仍保留。")
                            self._write_owned(path, state, owner)
            return self.status_fn(self.platform.root, tid, sku, current_draft=draft)

    @staticmethod
    def _write_owned(path, state, owner):
        current = read_json(path)
        if not owner.held or owner.stream.closed or not _same_state_identity(current, state):
            raise ValueError("生成工作身分已變更，拒絕舊工作覆寫狀態")
        atomic_json(path, state)

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
            owner = PreviewOwnership(path.parent)
            try:
                scavenge_state_temps(path, owner)
                atomic_json(path, state)  # Initial identity commit under OS ownership.
                self.tasks[key] = (task_id, stop)
                self.executor.submit(self._run, key, item, path, state, stop, owner)
            except BaseException:
                self.tasks.pop(key, None)
                owner.close()
                raise
            return {"taskId": task_id, "state": "queued"}

    def _run(self, key, item, path, state, stop, owner):
        try:
            if stop.is_set():
                return
            with self.lock:
                state.update(state="running", progress=10)
                self._write_owned(path, state, owner)
            def on_job(job):
                with self.lock:
                    state.update(jobId=job.get("jobId"), progress=25)
                    self._write_owned(path, state, owner)
            (self.generate_fn or generate_recipe_3d_product)(self.platform, *key, item["draft"], revision=item["revision"],
                                      generation_id=state["taskId"], on_job=on_job, cancel_flag=stop)
            state.update(state="succeeded", progress=100)
        except Exception as exc:
            state.update(state="failed", error=str(exc)[:1000])
        finally:
            with self.lock:
                if stop.is_set() and state["state"] != "succeeded":
                    state.update(state="cancelled", error=None)
                try:
                    self._write_owned(path, state, owner)
                finally:
                    if self.tasks.get(key) == (state["taskId"], stop):
                        self.tasks.pop(key, None)
                    owner.close()

    def cancel(self, tid, sku, task_id):
        with self.lock:
            task = self.tasks.get((tid, sku))
            if task is None or task[0] != task_id:
                raise ValueError("此工作已結束，請重新整理狀態")
            task[1].set()
            return {"taskId": task_id, "cancelRequested": True}
