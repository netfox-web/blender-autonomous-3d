# PILOT_DEPLOYMENT_ACCEPTANCE

generatedAt: 2026-09-09T05:21:51.977026+00:00
pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.
This is a scoped Phase 421–480 truth set, not a replacement of the canonical six-file set.

| Check | Status | Evidence |
|---|---|---|
| FIXTURE/CHAOS workOrders | FIXTURE | `n=110` |
| no oversell | REAL_LOGIC | `subprocess/persistence scope=True` |
| material conservation | REAL_LOGIC | `True` |
| crash all-or-nothing | REAL_LOGIC | `in-process CrashInjected + subprocess after-staging` |
| stale writer blocked | REAL_LOGIC | `True` |
| station offline/lease/duplicate | FIXTURE | `{"offlineDenied": true, "duplicateAck": true, "duplicateComplete": true, "noDuplicateComplete": true, "leaseExpiry": true, "started": true, "crossTenantDenied": true}` |
| QC fail rework pass | FIXTURE | `{"failed": true, "passed": true, "rework": true}` |
| stale release rejected | FIXTURE | `True` |
| packing mismatch rejected | FIXTURE | `True` |
| journal tamper detected | REAL_LOGIC | `{"restartPreserved": true, "duplicateSuppressed": true, "tenantIsolated": true, "chainOkBefore": true, "journalHealthyBeforeTamper": true, "tamperDetected": true, "journalTamperDetected": true, "tamperDetectionIsolated": true, "sharedJournalHealthyAfterAcceptance": true, "scratch": {"journalHealthyBeforeTamper": true, "journalTamperDetected": true, "tamperDetectionIsolated": true, "scratchStatus": "BLOCKED_EVIDENCE", "scratchRoot": "E:\\projects\\\u958b\u767c Blender Autonomous 3D\\.fox3d-data\\acceptance\\3d04bc63-a132-4e11-9409-fad65bcf8264\\journal-tamper\\966c9458-0cb5-498c-9939-f6ff02315268"}}` |
| journalHealthyBeforeTamper | REAL_LOGIC | `True` |
| sharedJournalHealthyAfterAcceptance | REAL_LOGIC | `True` |
| tamperDetectionIsolated | REAL_LOGIC | `True` |
| scan tenant isolation | FIXTURE | `True` |
| human approval gate | FIXTURE | `confirm required` |
| evidenceCodeCommit | REAL_LOGIC | `018cc70997a420e82358c0bb37677aa6b4de7eeb` |
| workingTreeClean | REAL_LOGIC | `True` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |
| LIVE_LASER | BLOCKED | `liveMachineControl=false` |
| not factory throughput | FIXTURE | `FIXTURE/CHAOS` |

`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.
