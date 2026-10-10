# PR #13 watchdog attempt d5d7140b — root cause note

**Evidence class: PARTIAL**

| Layer | Class | Why |
|---|---|---|
| Host stop mechanism | REAL_LOGIC | Read from source at the SHAs below. Not executed in this investigation. |
| Recorded attempt identity | Historical acceptance record | Committed JSON/Markdown on PR #13. This worker did not re-run the attempt and does not promote that record to a new REAL_RENDER. |
| Why the frame-0 depth call failed to return | BLOCKED | No Blender log, no progress-file bytes, and no Blender binary in this investigation environment. |
| This VM | NOT REAL | Synthetic inspection of git history and GitHub text. CI is not REAL. |

This note does not change PR #13, does not claim the attempt passed, and does not claim production readiness.

## Investigation binding

- Investigator: worker `bc-6b95bfac-9463-5dfa-9c50-4d18481baad8`.
- Clock: 2026-10-10T06:20:10Z (`date -u` on the investigation VM).
- Environment: Linux `6.12.94+`, x86_64, CPython 3.12.3. `blender` is not on `PATH` and `/usr/bin/blender` is absent. No REAL Blender, OptiX, or GPU render was run here.
- Canonical main used for the host-loop comparison: `b8c6fe911e6c8358ed7bcdecafc84cab86630810`. Main Actions [35957962415](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/35957962415) is SUCCESS on Ubuntu and Windows and is MOCK regression only.
- PR #13 head read with `git fetch` / `git show` / `git grep` (the branch was not checked out and was not modified): `3c57849f2a765451a3c03c564bbe6346e26ea9cd` on `codex/video-ground-truth`.
- CODE named by the attempt record: `a5b368a3d907950c5165f4b1a0058853ace617fc`.
- Acceptance files that contain the attempt: `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ROUND2_ACCEPTANCE.md` and `.json`, and the same `excludedFormalRuns` entry in `docs/GENERATIVE_VIDEO_GROUND_TRUTH_ACCEPTANCE.json`, at PR #13 head `3c57849`.
- Issue #1 comment [5854087167](https://github.com/netfox-web/blender-autonomous-3d/issues/1#issuecomment-5854087167) (2026-09-27T08:09:02Z) still describes this failure as an undetermined root cause. This note narrows the stop mechanism and leaves the in-process reason blocked.
- PR #13 issue comments and a GitHub issue search for `d5d7140b` on 2026-10-10 returned no separate log or comment beyond those committed acceptance files. Issue #6 comment [5672274860](https://github.com/netfox-web/blender-autonomous-3d/issues/6#issuecomment-5672274860) (2026-09-14T23:32:04Z) is the successful-generation handoff, not a log of this failure.

## What the acceptance record says

`excludedFormalRuns` at CODE `a5b368a3d907950c5165f4b1a0058853ace617fc`:

- `generationId`: `d5d7140b-4b9a-420b-a75d-2c3be56ac3d3`
- `status`: `FAILED_TIMEOUT`
- `lastProgress`: `video_frame_0_depth`
- `completedBeautyFrames`: `1`
- recorded `rootCause`: `UNDETERMINED; existing 120-second no-progress watchdog stopped worker; excluded from PASS.`

The record does not include a timestamp, hostname, Blender version, device, sequence id, sample count, or `blender.log` excerpt for this generation. Those values are not inferred here. The later successful generation `d320a651-c2a4-403e-9322-a37630fcea6e` on the same CODE records Blender 5.2.1 LTS / OPTIX and `usedMock=false` for its own outputs. That success does not explain this failure and does not erase it.

A different sentence in the Round 2 acceptance Markdown ("one HERO stalled before output") is an earlier development exclusion. This formal attempt completed one beauty frame, so it is not that earlier stall.

## Stop mechanism (REAL_LOGIC)

Video passes are separate stills. In `scripts/blender_video_job.py` at PR #13 head, each role writes progress once and then blocks inside Blender:

```python
core._write_progress(job, (index + pass_index / len(roles)) / recipe["frameCount"], f"video_frame_{index}_{role}")
# compositor setup for that role
bpy.ops.render.render(write_still=True)
```

`ROLES` order in `src/fox3d/video_recipe.py` is `beauty`, `depth`, `normal`, `product_mask`, `artwork_mask`, `alpha` (`context_mask` is appended only for `SMALL_ROOM_10S`). Stage `video_frame_0_depth` is therefore frame index 0, the depth role, written immediately before that role's `bpy.ops.render.render(write_still=True)`. The next progress write happens only after that call returns. `completedBeautyFrames: 1` matches the preceding beauty still having finished and its file existing.

The host loop in `src/fox3d/blender.py` (same control flow on main `b8c6fe9` and on PR #13 CODE `a5b368a`) resets its stall clock only when the numeric `progress` field changes. It does not read `stage`. The video caller uses `timeout_seconds=14400` (`src/fox3d/video_ground_truth.py`), so the binding limit is the hard-coded 120-second stall, not the job timeout:

```python
value = float(payload.get("progress") or 0)
if value != last_progress_val:
    last_progress_val = value
    last_progress_at = now
if now - last_progress_at > 120:
    proc.kill()
    return RuntimeResult(status="timeout", error="stall watchdog: no progress for 120s", log="".join(log), ...)
```

Depth's numeric progress is not equal to beauty's. For the default recipes, frame 0 beauty writes `0.0` and frame 0 depth writes `(1 / len(roles)) / frameCount` (6 roles, or 7 when a room mask is included). Those floats differ, so a successful read of the depth progress file resets the 120-second window at the start of the depth still. The watchdog then fires only if that still does not return, and no later progress float is observed, for 120 seconds.

Default recipes are 128×128, Cycles `samples=4`, 12 fps (`make_recipe` in `src/fox3d/video_recipe.py`). A healthy still of that size is not specified as a 120-second render. The same CODE later completed 288 frames (1728 product control artifacts plus 120 room masks). The depth call on this attempt is therefore a call that did not return inside the watchdog window, not a recipe that requires more than 120 seconds per pass.

## Why the historical label stayed UNDETERMINED (REAL_LOGIC)

On the stall return path, `log` is still empty. `blender.log` is appended only after `proc.poll()` reports a normal exit. `platform.execute_job` stores `job["logs"]` from that empty string. Killing the process also prevents the worker from writing a useful `result.json`. No tracked code writes `lastProgress` or `completedBeautyFrames`; those fields exist only in the hand-authored acceptance JSON. The raw directory named for the successful generation, `.fox3d-work/video-round2-e2e/d320a651/`, is not the failed generation and is not in git.

So the acceptance authors could see the progress stage and a beauty-frame count, and could not see Blender's stdout. That is why the committed root cause is the watchdog sentence plus `UNDETERMINED`.

## What remains BLOCKED

This investigation cannot tell which of the following kept `bpy.ops.render.render(write_still=True)` from returning on the frame-0 depth still:

- an OptiX / driver stall after the beauty pass;
- a hang while switching that still from PNG to 32-bit OpenEXR;
- a lost progress read (partial JSON write or an exception swallowed by the host `JSONDecodeError` / `OSError` / `ValueError` handler), so the 120 seconds were measured from an earlier float;
- any other in-process Blender failure.

Those distinctions need the missing `blender.log` and `progress.json` bytes, or a new real run. This VM cannot produce that run. A green pytest job would be MOCK and would not answer it.

No code change is made to the watchdog or the video worker in this note. PR #13's branch is unchanged.
