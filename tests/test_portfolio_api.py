"""Portfolio HTTP API — tenant scope, ranking, approval idempotency."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.platform import Platform
from fox3d.portfolio import run_portfolio_scenario

TENANT_A = "pf-api-a"
TENANT_B = "pf-api-b"
CONFIRM = {"confirm": True, "actor": "pm", "reason": "approve-once"}


@pytest.fixture()
def client(platform):  # noqa: ANN001
    return TestClient(create_app(platform))


def _h(tenant: str = TENANT_A) -> dict[str, str]:
    return {"X-Tenant-Id": tenant}


def _flow(client: TestClient) -> dict:
    intent = client.post("/api/portfolio/intents", headers=_h(), json={"segment": "STUDENT", "demandSource": "MOCK"}).json()
    pid = intent["portfolioId"]
    gen = client.post(f"/api/portfolio/intents/{pid}/candidates", headers=_h()).json()
    assert gen["count"] >= 1
    plan = client.post(f"/api/portfolio/intents/{pid}/material-plan", headers=_h(), json={}).json()
    assert plan["planId"]
    ranking = client.post(f"/api/portfolio/intents/{pid}/rankings", headers=_h(), json={}).json()
    assert ranking["demandReal"] is False
    assert ranking.get("demandEstimateLabel") == "需求為估計值"
    top = ranking["top10"][0]["candidateId"]
    return {
        "portfolioId": pid,
        "rankingId": ranking["rankingId"],
        "topCandidateId": top,
        "ranking": ranking,
        "plan": plan,
    }


def test_portfolio_api_full_flow_and_persistence(client: TestClient, platform) -> None:
    data = _flow(client)
    listing = client.get("/api/portfolio/intents", headers=_h()).json()
    assert listing["total"] >= 1
    one = client.get(f"/api/portfolio/intents/{data['portfolioId']}", headers=_h()).json()
    assert one["portfolioId"] == data["portfolioId"]
    cands = client.get(f"/api/portfolio/intents/{data['portfolioId']}/candidates", headers=_h()).json()
    assert cands["total"] >= 10
    assert client.get(f"/api/portfolio/candidates/{data['topCandidateId']}/media-pack", headers=_h()).status_code == 200
    path = platform.portfolio.root / "portfolio.json"
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    assert client.get(f"/api/portfolio/intents/{data['portfolioId']}", headers=_h()).status_code == 200
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime

    submit = client.post(
        f"/api/portfolio/candidates/{data['topCandidateId']}/submit-approval",
        headers=_h(),
        json={"actor": "pm"},
    )
    assert submit.status_code == 200
    approval_id = submit.json()["approvalId"]
    first = client.post(f"/api/portfolio/approvals/{approval_id}/approve", headers=_h(), json=CONFIRM)
    second = client.post(f"/api/portfolio/approvals/{approval_id}/approve", headers=_h(), json=CONFIRM)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json().get("approvedAt") == second.json().get("approvedAt")

    pack = client.get(f"/api/portfolio/candidates/{data['topCandidateId']}/prototype-pack", headers=_h())
    assert pack.status_code == 200
    assert pack.json().get("readyForManualPrototype") is True

    reloaded = Platform(root=platform.root, mock_blender=True)
    c2 = TestClient(create_app(reloaded))
    assert c2.get(f"/api/portfolio/intents/{data['portfolioId']}", headers=_h()).json()["portfolioId"] == data["portfolioId"]


def test_cross_tenant_is_404_without_leak(client: TestClient) -> None:
    data = _flow(client)
    for suffix in (
        "",
        f"/{data['portfolioId']}",
        f"/{data['portfolioId']}/candidates",
        f"/{data['portfolioId']}/material-plan",
        f"/{data['portfolioId']}/rankings",
    ):
        method = "post" if suffix.endswith(("candidates", "material-plan", "rankings")) else "get"
        url = "/api/portfolio/intents" + suffix
        if method == "post":
            res = client.post(url, headers=_h(TENANT_B), json={})
        else:
            res = client.get(url if suffix else "/api/portfolio/intents", headers=_h(TENANT_B))
        if not suffix:
            assert res.status_code == 200
            assert res.json()["total"] == 0
            continue
        assert res.status_code in {404, 405}
        assert "KeyError" not in res.text
        assert "tenant isolation" not in res.text
    for path in (
        f"/api/portfolio/rankings/{data['rankingId']}/override",
        f"/api/portfolio/candidates/{data['topCandidateId']}/submit-approval",
        f"/api/portfolio/approvals/x/submit",
        f"/api/portfolio/candidates/{data['topCandidateId']}/supersede",
        f"/api/portfolio/candidates/{data['topCandidateId']}/prototype-pack",
    ):
        res = client.post(path, headers=_h(TENANT_B), json={"actor": "x", "reason": "x", "candidateId": data["topCandidateId"]})
        if res.status_code == 405:
            res = client.get(path, headers=_h(TENANT_B))
        assert res.status_code in {400, 403, 404, 422}
        assert "KeyError" not in res.text


def test_override_missing_reason_is_422(client: TestClient) -> None:
    data = _flow(client)
    res = client.post(
        f"/api/portfolio/rankings/{data['rankingId']}/override",
        headers=_h(),
        json={"actor": "planner", "candidateId": data["topCandidateId"]},
    )
    assert res.status_code == 422
    assert res.json()["detail"] == "reason 必填"


def test_approve_requires_confirm_token(client: TestClient) -> None:
    data = _flow(client)
    submit = client.post(
        f"/api/portfolio/candidates/{data['topCandidateId']}/submit-approval",
        headers=_h(),
        json={"actor": "pm"},
    ).json()
    res = client.post(
        f"/api/portfolio/approvals/{submit['approvalId']}/approve",
        headers=_h(),
        json={"actor": "pm", "reason": "no-token"},
    )
    assert res.status_code == 403


def test_concurrent_approve_applies_once(client: TestClient) -> None:
    data = _flow(client)
    submit = client.post(
        f"/api/portfolio/candidates/{data['topCandidateId']}/submit-approval",
        headers=_h(),
        json={"actor": "pm"},
    ).json()
    aid = submit["approvalId"]

    def once() -> dict:
        return client.post(f"/api/portfolio/approvals/{aid}/approve", headers=_h(), json=CONFIRM).json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda _: once(), range(2)))
    assert a.get("approvedAt") == b.get("approvedAt")
    assert a.get("status") == "APPROVED_FOR_PROTOTYPE"


def test_stale_cost_hint_in_ranking(client: TestClient, platform) -> None:
    data = _flow(client)
    cid = data["topCandidateId"]
    rec = platform.portfolio.candidates[cid]
    rec["commercial"]["engineeringHash"] = "stale-hash"
    rec["commercial"]["stale"] = True
    platform.portfolio.persist()
    ranking = client.post(
        f"/api/portfolio/intents/{data['portfolioId']}/rankings",
        headers=_h(),
        json={},
    ).json()
    assert cid in (ranking.get("staleCostHints") or [])
    pack = client.get(f"/api/portfolio/candidates/{cid}/prototype-pack", headers=_h())
    assert pack.status_code == 400
    assert "KeyError" not in pack.text


def test_supersede_blocks_prototype_pack(client: TestClient) -> None:
    data = _flow(client)
    cid = data["topCandidateId"]
    assert client.post(f"/api/portfolio/candidates/{cid}/supersede", headers=_h()).status_code == 200
    res = client.get(f"/api/portfolio/candidates/{cid}/prototype-pack", headers=_h())
    assert res.status_code == 400


def test_scenario_via_factory_matches_http(client: TestClient, tmp_path) -> None:
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a=TENANT_A, tenant_b=TENANT_B)
    c = TestClient(create_app(plat))
    pid = next(i["portfolioId"] for i in plat.portfolio.intents.values() if i["tenantId"] == TENANT_A)
    ranking = c.post(f"/api/portfolio/intents/{pid}/rankings", headers=_h(TENANT_A), json={}).json()
    assert ranking["demandReal"] is False
    assert len(ranking["top10"]) == 10