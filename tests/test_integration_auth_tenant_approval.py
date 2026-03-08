from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import app.api.routes.chat as chat_routes
from app.main import app
from app.services.approvals import create_approval_request


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _headers(token: str, tenant_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    return headers


def test_approval_workflow_with_tenant_and_user_isolation(monkeypatch) -> None:
    suffix = uuid4().hex[:8]
    tenant_primary = f"tenant-{suffix}-a"
    tenant_secondary = f"tenant-{suffix}-b"
    alice_username = f"alice-{suffix}"
    bob_username = f"bob-{suffix}"

    def fake_run_workflow(question: str, tenant_id: str, user_id: str) -> dict:
        approval_id = create_approval_request(
            user_id=user_id,
            tenant_id=tenant_id,
            question=question,
            draft_answer=f"draft-answer-for-{question}",
        )
        return {
            "question": question,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "retrieved": [("mock-context", 0.99, "mock-source", [1])],
            "draft_answer": "mock-draft",
            "approval_required": True,
            "approval_id": approval_id,
        }

    monkeypatch.setattr(chat_routes, "run_workflow", fake_run_workflow)

    with TestClient(app, base_url="http://localhost") as client:
        admin = _login(client, "demo", "demo123")
        admin_token = admin["access_token"]
        admin_user_id = admin["user_id"]

        create_tenant_primary = client.post(
            "/api/tenants/",
            json={"tenant_id": tenant_primary, "name": tenant_primary},
            headers=_headers(admin_token),
        )
        assert create_tenant_primary.status_code == 200, create_tenant_primary.text

        create_tenant_secondary = client.post(
            "/api/tenants/",
            json={"tenant_id": tenant_secondary, "name": tenant_secondary},
            headers=_headers(admin_token),
        )
        assert create_tenant_secondary.status_code == 200, create_tenant_secondary.text

        # Admin must be explicitly assigned to tenant_primary in this RBAC model.
        assign_admin = client.post(
            f"/api/users/{admin_user_id}/tenants",
            json={"tenant_id": tenant_primary},
            headers=_headers(admin_token),
        )
        assert assign_admin.status_code == 200, assign_admin.text

        create_alice = client.post(
            "/api/users/",
            json={
                "username": alice_username,
                "password": "alice-pass-123",
                "role": "user",
                "default_tenant_id": tenant_primary,
            },
            headers=_headers(admin_token),
        )
        assert create_alice.status_code == 200, create_alice.text

        create_bob = client.post(
            "/api/users/",
            json={
                "username": bob_username,
                "password": "bob-pass-123",
                "role": "user",
                "default_tenant_id": tenant_primary,
            },
            headers=_headers(admin_token),
        )
        assert create_bob.status_code == 200, create_bob.text

        alice = _login(client, alice_username, "alice-pass-123")
        bob = _login(client, bob_username, "bob-pass-123")

        alice_chat = client.post(
            "/api/chat/",
            json={"question": "What is our escalation policy?"},
            headers=_headers(alice["access_token"], tenant_primary),
        )
        assert alice_chat.status_code == 200, alice_chat.text
        payload = alice_chat.json()
        assert payload["status"] == "pending_approval"
        assert payload["approval_id"]
        approval_id = payload["approval_id"]

        bob_cannot_view = client.get(
            f"/api/approvals/{approval_id}/result",
            headers=_headers(bob["access_token"], tenant_primary),
        )
        assert bob_cannot_view.status_code == 403

        alice_pending = client.get(
            f"/api/approvals/{approval_id}/result",
            headers=_headers(alice["access_token"], tenant_primary),
        )
        assert alice_pending.status_code == 200
        assert alice_pending.json()["status"] == "pending"

        alice_cannot_decide = client.post(
            f"/api/approvals/{approval_id}/decision",
            json={"approved": True, "note": "approve"},
            headers=_headers(alice["access_token"]),
        )
        assert alice_cannot_decide.status_code == 403

        admin_approvals = client.get(
            f"/api/approvals/?status=pending&tenant_id={tenant_primary}",
            headers=_headers(admin_token),
        )
        assert admin_approvals.status_code == 200, admin_approvals.text
        assert any(item["approval_id"] == approval_id for item in admin_approvals.json())

        admin_decide = client.post(
            f"/api/approvals/{approval_id}/decision",
            json={"approved": True, "note": "Approved by integration test"},
            headers=_headers(admin_token),
        )
        assert admin_decide.status_code == 200, admin_decide.text
        assert admin_decide.json()["status"] == "approved"

        alice_approved = client.get(
            f"/api/approvals/{approval_id}/result",
            headers=_headers(alice["access_token"], tenant_primary),
        )
        assert alice_approved.status_code == 200
        assert alice_approved.json()["status"] == "approved"
        assert alice_approved.json()["final_answer"] == "draft-answer-for-What is our escalation policy?"

        alice_wrong_tenant = client.get(
            f"/api/approvals/{approval_id}/result",
            headers=_headers(alice["access_token"], tenant_secondary),
        )
        assert alice_wrong_tenant.status_code == 403


def test_chat_rejects_unassigned_tenant_access(monkeypatch) -> None:
    suffix = uuid4().hex[:8]
    tenant_allowed = f"tenant-{suffix}-allowed"
    tenant_blocked = f"tenant-{suffix}-blocked"
    username = f"tenant-user-{suffix}"

    # Prevent accidental external LLM/vector calls if route-level deps change.
    monkeypatch.setattr(
        chat_routes,
        "run_workflow",
        lambda question, tenant_id, user_id: {
            "question": question,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "retrieved": [],
            "draft_answer": "mock",
            "approval_required": False,
        },
    )

    with TestClient(app, base_url="http://localhost") as client:
        admin = _login(client, "demo", "demo123")
        admin_token = admin["access_token"]

        for tenant_id in (tenant_allowed, tenant_blocked):
            response = client.post(
                "/api/tenants/",
                json={"tenant_id": tenant_id, "name": tenant_id},
                headers=_headers(admin_token),
            )
            assert response.status_code == 200, response.text

        create_user = client.post(
            "/api/users/",
            json={
                "username": username,
                "password": "tenant-pass-123",
                "role": "user",
                "default_tenant_id": tenant_allowed,
            },
            headers=_headers(admin_token),
        )
        assert create_user.status_code == 200, create_user.text

        user_login = _login(client, username, "tenant-pass-123")

        denied = client.post(
            "/api/chat/",
            json={"question": "Can I access blocked tenant data?"},
            headers=_headers(user_login["access_token"], tenant_blocked),
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == "Tenant access denied"
