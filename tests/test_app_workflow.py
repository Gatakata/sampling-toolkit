import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DB_FILE = ROOT / "data" / "test_audit_sampling.sqlite3"
os.environ["DB_PATH"] = str(DB_FILE)

sys.path.insert(0, str(ROOT / "app" / "backend"))

from app import app  # noqa: E402
from db import get_connection, initialize_database  # noqa: E402
from sampling import judgemental_sampling, mus_sampling, stratified_sampling  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    initialize_database()
    with get_connection() as conn:
        conn.execute("DELETE FROM sample_output")
        conn.execute("DELETE FROM sample_runs")
        conn.execute("DELETE FROM population")
        conn.execute("DELETE FROM audit_log")
        conn.execute("DELETE FROM engagements")
        conn.execute("DELETE FROM admin_sessions")
        conn.execute("DELETE FROM admin_users WHERE username <> 'Taku'")
        conn.commit()
    yield


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def auth_headers(client):
    login = client.post(
        "/api/admin/login",
        json={"username": "Taku", "password": "Taku2002!"},
    )
    assert login.status_code == 200
    token = login.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def create_engagement(client, headers):
    payload = {
        "client_name": "Acme Corp",
        "engagement_ref": "ENG-2026-01",
        "auditor_name": "Taku",
        "financial_year": "2026",
        "materiality_benchmark": "Total Assets",
        "materiality_base": 124059,
        "materiality_percent": 2,
        "materiality": 1000,
        "performance_percent": 75,
        "performance_materiality": 750,
        "clearly_trivial_percent": 3,
        "clearly_trivial_threshold": 40,
    }
    response = client.post("/api/engagements", json=payload, headers=headers)
    assert response.status_code == 201
    return response.get_json()["id"]


def user_payload(username, password, first_name="Taku", surname="Tester", is_admin=False):
    return {
        "username": username,
        "first_name": first_name,
        "surname": surname,
        "email": f"{username}@example.com",
        "password": password,
        "is_admin": is_admin,
    }


def test_database_initializes_core_tables(client):
    with get_connection() as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "admin_users" in names
    assert "admin_sessions" in names
    assert "engagements" in names
    assert "population" in names
    assert "sample_runs" in names
    assert "sample_output" in names
    assert "audit_log" in names


def test_authentication_required_for_protected_routes(client):
    response = client.get("/api/engagements")
    assert response.status_code == 401


def test_only_admin_can_create_users(client):
    admin_headers = auth_headers(client)
    create_response = client.post(
        "/api/users",
        json=user_payload("analyst1", "StrongPass123!", first_name="Ava", surname="Analyst"),
        headers=admin_headers,
    )
    assert create_response.status_code == 201

    user_login = client.post(
        "/api/auth/login",
        json={"username": "analyst1", "password": "StrongPass123!"},
    )
    assert user_login.status_code == 200
    user_token = user_login.get_json()["token"]

    non_admin_create = client.post(
        "/api/users",
        json=user_payload("analyst2", "StrongPass123!", first_name="Ben", surname="Broker"),
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert non_admin_create.status_code == 403


def test_password_policy_rejects_weak_password(client):
    admin_headers = auth_headers(client)
    response = client.post(
        "/api/users",
        json=user_payload("weakuser", "weakpass", first_name="Weak", surname="User"),
        headers=admin_headers,
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert "password" in body["errors"]


def test_must_reset_password_does_not_block_protected_api(client):
    admin_headers = auth_headers(client)
    create = client.post(
        "/api/users",
        json=user_payload("newjoiner", "TempPass123!", first_name="Nora", surname="Joiner"),
        headers=admin_headers,
    )
    assert create.status_code == 201

    login = client.post(
        "/api/auth/login",
        json={"username": "newjoiner", "password": "TempPass123!"},
    )
    assert login.status_code == 200
    assert bool(login.get_json()["user"]["must_reset_password"]) is True
    token = login.get_json()["token"]

    accessible = client.get("/api/engagements", headers={"Authorization": f"Bearer {token}"})
    assert accessible.status_code == 200

    change = client.post(
        "/api/auth/change-password",
        json={"current_password": "TempPass123!", "new_password": "NewPass123!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert change.status_code == 200

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert bool(me.get_json()["must_reset_password"]) is False


def test_admin_can_disable_and_enable_user(client):
    admin_headers = auth_headers(client)
    create = client.post(
        "/api/users",
        json=user_payload("toggleuser", "TogglePass123!", first_name="Tara", surname="Toggle"),
        headers=admin_headers,
    )
    assert create.status_code == 201
    user_id = create.get_json()["id"]

    disable = client.patch(
        f"/api/users/{user_id}/status",
        json={"is_active": False},
        headers=admin_headers,
    )
    assert disable.status_code == 200
    assert disable.get_json()["is_active"] == 0

    login = client.post(
        "/api/auth/login",
        json={"username": "toggleuser", "password": "TogglePass123!"},
    )
    assert login.status_code == 403
    assert login.get_json()["code"] == "ACCOUNT_DISABLED"

    enable = client.patch(
        f"/api/users/{user_id}/status",
        json={"is_active": True},
        headers=admin_headers,
    )
    assert enable.status_code == 200
    assert enable.get_json()["is_active"] == 1


def test_account_lockout_after_repeated_failed_logins(client):
    admin_headers = auth_headers(client)
    create = client.post(
        "/api/users",
        json=user_payload("lockme", "LockMePass123!", first_name="Leo", surname="Lock"),
        headers=admin_headers,
    )
    assert create.status_code == 201

    # Fail enough times to trigger lockout.
    lock_response = None
    for _ in range(5):
        lock_response = client.post(
            "/api/auth/login",
            json={"username": "lockme", "password": "WrongPass123!"},
        )
    assert lock_response is not None
    assert lock_response.status_code == 423
    body = lock_response.get_json()
    assert body["code"] == "ACCOUNT_LOCKED"
    assert body.get("locked_until")

    # Correct password should still be blocked while locked.
    blocked = client.post(
        "/api/auth/login",
        json={"username": "lockme", "password": "LockMePass123!"},
    )
    assert blocked.status_code == 423
    assert blocked.get_json()["code"] == "ACCOUNT_LOCKED"


def test_security_events_written_to_audit_log(client):
    admin_headers = auth_headers(client)

    create = client.post(
        "/api/users",
        json=user_payload("auditeduser", "AuditedPass123!", first_name="Ada", surname="Audit"),
        headers=admin_headers,
    )
    assert create.status_code == 201
    user_id = create.get_json()["id"]

    client.post(
        "/api/auth/login",
        json={"username": "auditeduser", "password": "WrongPass123!"},
    )

    set_password = client.patch(
        f"/api/users/{user_id}/password",
        json={"new_password": "AuditedPass456!", "must_reset_password": True},
        headers=admin_headers,
    )
    assert set_password.status_code == 200

    logs = client.get("/api/audit-log", headers=admin_headers)
    assert logs.status_code == 200
    event_types = [row["event_type"] for row in logs.get_json()]
    assert "user_created" in event_types
    assert "login_failed" in event_types
    assert "user_password_set" in event_types


def test_three_tier_materiality_population_summary_and_sampling_window(client):
    headers = auth_headers(client)
    engagement_id = create_engagement(client, headers)

    rows = [
        {
            "transaction_ref": "TXN-TRIVIAL",
            "account_code": "1000",
            "description": "Below clearly trivial",
            "transaction_date": "2026-01-01",
            "amount": 20,
        },
        {
            "transaction_ref": "TXN-SAMPLE-1",
            "account_code": "1000",
            "description": "Sampling population item 1",
            "transaction_date": "2026-01-02",
            "amount": 100,
        },
        {
            "transaction_ref": "TXN-SAMPLE-2",
            "account_code": "1000",
            "description": "Sampling population item 2",
            "transaction_date": "2026-01-03",
            "amount": 700,
        },
        {
            "transaction_ref": "TXN-HIGH",
            "account_code": "1000",
            "description": "Above performance materiality",
            "transaction_date": "2026-01-04",
            "amount": 900,
        },
    ]

    imported = client.post(
        f"/api/engagements/{engagement_id}/population",
        json=rows,
        headers=headers,
    )
    assert imported.status_code == 201

    summary = client.get(
        f"/api/engagements/{engagement_id}/population/summary?performance_materiality=750&clearly_trivial_threshold=40",
        headers=headers,
    )
    assert summary.status_code == 200
    body = summary.get_json()
    assert body["total_items"] == 4
    assert body["items_above_performance_materiality"] == 1
    assert body["sampling_population_items"] == 2
    assert body["items_below_clearly_trivial"] == 1

    run = client.post(
        f"/api/engagements/{engagement_id}/run-sample",
        json={
            "sampling_method": "random",
            "sample_size": 2,
            "materiality": 1000,
            "performance_materiality": 750,
            "clearly_trivial_threshold": 40,
            "confidence_level": 95,
            "expected_error_rate": 1,
            "tolerable_error_rate": 5,
            "auditor_name": "Taku",
            "random_seed": 7,
        },
        headers=headers,
    )
    assert run.status_code == 201
    run_body = run.get_json()["run"]
    assert float(run_body["performance_materiality"]) == 750
    assert float(run_body["clearly_trivial_threshold"]) == 40

    output = client.get(f"/api/runs/{run_body['id']}/output", headers=headers)
    assert output.status_code == 200
    refs = {row["transaction_ref"] for row in output.get_json()}
    assert "TXN-TRIVIAL" not in refs
    assert "TXN-HIGH" in refs


def test_materiality_percent_outside_benchmark_range_is_rejected(client):
    headers = auth_headers(client)
    response = client.post(
        "/api/engagements",
        json={
            "client_name": "Invalid Bench",
            "engagement_ref": "ENG-INVALID-01",
            "auditor_name": "Taku",
            "financial_year": "2026",
            "materiality_benchmark": "Total Assets",
            "materiality_base": 100000,
            "materiality_percent": 5,  # outside 1%-2%
            "materiality": 5000,
            "performance_percent": 75,
            "performance_materiality": 3750,
            "clearly_trivial_percent": 3,
            "clearly_trivial_threshold": 113,
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert "between" in response.get_json()["error"]


def test_population_upload_rejects_missing_transaction_ref(client):
    headers = auth_headers(client)
    engagement_id = create_engagement(client, headers)
    response = client.post(
        f"/api/engagements/{engagement_id}/population",
        json=[
            {
                "transaction_ref": "",
                "account_code": "1000",
                "description": "Invalid row",
                "transaction_date": "2026-01-01",
                "amount": 10,
            }
        ],
        headers=headers,
    )
    assert response.status_code == 400
    assert "transaction_ref" in response.get_json()["error"]


def test_run_sample_rejects_invalid_threshold_order(client):
    headers = auth_headers(client)
    engagement_id = create_engagement(client, headers)

    client.post(
        f"/api/engagements/{engagement_id}/population",
        json=[
            {
                "transaction_ref": "TXN-1",
                "account_code": "1000",
                "description": "Row",
                "transaction_date": "2026-01-01",
                "amount": 100,
            }
        ],
        headers=headers,
    )

    response = client.post(
        f"/api/engagements/{engagement_id}/run-sample",
        json={
            "sampling_method": "random",
            "sample_size": 1,
            "materiality": 1000,
            "performance_materiality": 100,
            "clearly_trivial_threshold": 150,  # invalid: CT > PM
            "confidence_level": 95,
            "expected_error_rate": 1,
            "tolerable_error_rate": 5,
            "auditor_name": "Taku",
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert "cannot exceed" in response.get_json()["error"]


def test_population_import_handles_duplicates(client):
    headers = auth_headers(client)
    engagement_id = create_engagement(client, headers)

    rows = [
        {
            "transaction_ref": "TXN-1",
            "account_code": "4000",
            "description": "Revenue item",
            "transaction_date": "2026-01-02",
            "amount": 1200,
        },
        {
            "transaction_ref": "TXN-1",
            "account_code": "4000",
            "description": "Duplicate revenue item",
            "transaction_date": "2026-01-03",
            "amount": 900,
        },
    ]

    response = client.post(
        f"/api/engagements/{engagement_id}/population",
        json=rows,
        headers=headers,
    )
    assert response.status_code == 201
    payload = response.get_json()
    assert payload["inserted"] == 1
    assert payload["duplicates"] == ["TXN-1"]


def test_sample_run_excludes_high_value_from_random_and_auto_adds(client):
    headers = auth_headers(client)
    engagement_id = create_engagement(client, headers)

    rows = [
        {
            "transaction_ref": "TXN-LOW-1",
            "account_code": "1000",
            "description": "Low one",
            "transaction_date": "2026-01-01",
            "amount": 100,
        },
        {
            "transaction_ref": "TXN-LOW-2",
            "account_code": "1000",
            "description": "Low two",
            "transaction_date": "2026-01-02",
            "amount": 150,
        },
        {
            "transaction_ref": "TXN-HIGH-1",
            "account_code": "9000",
            "description": "High value",
            "transaction_date": "2026-01-03",
            "amount": 2500,
        },
    ]

    import_response = client.post(
        f"/api/engagements/{engagement_id}/population",
        json=rows,
        headers=headers,
    )
    assert import_response.status_code == 201

    run_response = client.post(
        f"/api/engagements/{engagement_id}/run-sample",
        json={
            "sampling_method": "random",
            "sample_size": 1,
            "materiality": 1000,
            "confidence_level": 95,
            "expected_error_rate": 1,
            "tolerable_error_rate": 5,
            "auditor_name": "Taku",
            "random_seed": 42,
        },
        headers=headers,
    )
    assert run_response.status_code == 201
    run_id = run_response.get_json()["run"]["id"]

    output = client.get(f"/api/runs/{run_id}/output", headers=headers)
    assert output.status_code == 200
    refs = {row["transaction_ref"] for row in output.get_json()}
    assert "TXN-HIGH-1" in refs

    high_value = client.get(f"/api/runs/{run_id}/high-value", headers=headers)
    assert high_value.status_code == 200
    assert len(high_value.get_json()) == 1


def test_random_sample_accepts_zero_tolerable_error_rate(client):
    headers = auth_headers(client)
    engagement_id = create_engagement(client, headers)

    rows = [
        {
            "transaction_ref": "TXN-RAND-1",
            "account_code": "1000",
            "description": "Random candidate one",
            "transaction_date": "2026-01-01",
            "amount": 100,
        },
        {
            "transaction_ref": "TXN-RAND-2",
            "account_code": "1000",
            "description": "Random candidate two",
            "transaction_date": "2026-01-02",
            "amount": 200,
        },
        {
            "transaction_ref": "TXN-RAND-3",
            "account_code": "1000",
            "description": "Random candidate three",
            "transaction_date": "2026-01-03",
            "amount": 300,
        },
    ]

    imported = client.post(
        f"/api/engagements/{engagement_id}/population",
        json=rows,
        headers=headers,
    )
    assert imported.status_code == 201

    run_response = client.post(
        f"/api/engagements/{engagement_id}/run-sample",
        json={
            "sampling_method": "random",
            "sample_size": 2,
            "materiality": 1000,
            "performance_materiality": 750,
            "clearly_trivial_threshold": 40,
            "confidence_level": 95,
            "expected_error_rate": 1,
            "tolerable_error_rate": 0,
            "auditor_name": "Taku",
            "random_seed": 7,
        },
        headers=headers,
    )
    assert run_response.status_code == 201


def test_random_sample_accepts_tolerable_error_rate_above_100(client):
    headers = auth_headers(client)
    engagement_id = create_engagement(client, headers)

    rows = [
        {
            "transaction_ref": "TXN-HI-TOL-1",
            "account_code": "1000",
            "description": "Random candidate one",
            "transaction_date": "2026-01-01",
            "amount": 100,
        },
        {
            "transaction_ref": "TXN-HI-TOL-2",
            "account_code": "1000",
            "description": "Random candidate two",
            "transaction_date": "2026-01-02",
            "amount": 200,
        },
        {
            "transaction_ref": "TXN-HI-TOL-3",
            "account_code": "1000",
            "description": "Random candidate three",
            "transaction_date": "2026-01-03",
            "amount": 300,
        },
    ]

    imported = client.post(
        f"/api/engagements/{engagement_id}/population",
        json=rows,
        headers=headers,
    )
    assert imported.status_code == 201

    run_response = client.post(
        f"/api/engagements/{engagement_id}/run-sample",
        json={
            "sampling_method": "random",
            "sample_size": 2,
            "materiality": 1000,
            "performance_materiality": 750,
            "clearly_trivial_threshold": 40,
            "confidence_level": 95,
            "expected_error_rate": 1,
            "tolerable_error_rate": 404.878,
            "auditor_name": "Taku",
            "random_seed": 7,
        },
        headers=headers,
    )
    assert run_response.status_code == 201


def _method_population_rows():
    return [
        {
            "transaction_ref": "TXN-METHOD-1",
            "account_code": "1000",
            "description": "Method coverage row 1",
            "transaction_date": "2026-01-01",
            "amount": 100,
        },
        {
            "transaction_ref": "TXN-METHOD-2",
            "account_code": "2000",
            "description": "Method coverage row 2",
            "transaction_date": "2026-01-02",
            "amount": 220,
        },
        {
            "transaction_ref": "TXN-METHOD-3",
            "account_code": "3000",
            "description": "Method coverage row 3",
            "transaction_date": "2026-01-03",
            "amount": 480,
        },
        {
            "transaction_ref": "TXN-METHOD-4",
            "account_code": "4000",
            "description": "Method coverage row 4",
            "transaction_date": "2026-01-04",
            "amount": 900,
        },
    ]


@pytest.mark.parametrize("method", ["systematic", "mus", "stratified", "judgemental"])
def test_all_sampling_methods_create_run_output(client, method):
    headers = auth_headers(client)
    engagement_id = create_engagement(client, headers)

    imported = client.post(
        f"/api/engagements/{engagement_id}/population",
        json=_method_population_rows(),
        headers=headers,
    )
    assert imported.status_code == 201

    population = client.get(f"/api/engagements/{engagement_id}/population", headers=headers)
    assert population.status_code == 200
    population_ids = [row["id"] for row in population.get_json()]

    payload = {
        "sampling_method": method,
        "sample_size": 2,
        "materiality": 1000,
        "performance_materiality": 750,
        "clearly_trivial_threshold": 40,
        "confidence_level": 95,
        "expected_error_rate": 1,
        "tolerable_error_rate": 5,
        "auditor_name": "Taku",
        "random_seed": 7,
    }
    if method == "judgemental":
        payload["manual_ids"] = population_ids[:2]

    run_response = client.post(
        f"/api/engagements/{engagement_id}/run-sample",
        json=payload,
        headers=headers,
    )
    assert run_response.status_code == 201
    run = run_response.get_json()["run"]
    assert run["sampling_method"] == method

    output = client.get(f"/api/runs/{run['id']}/output", headers=headers)
    assert output.status_code == 200
    assert len(output.get_json()) >= 1


def test_judgemental_sampling_requires_manual_ids(client):
    headers = auth_headers(client)
    engagement_id = create_engagement(client, headers)

    imported = client.post(
        f"/api/engagements/{engagement_id}/population",
        json=_method_population_rows(),
        headers=headers,
    )
    assert imported.status_code == 201

    response = client.post(
        f"/api/engagements/{engagement_id}/run-sample",
        json={
            "sampling_method": "judgemental",
            "sample_size": 2,
            "materiality": 1000,
            "performance_materiality": 750,
            "clearly_trivial_threshold": 40,
            "confidence_level": 95,
            "expected_error_rate": 1,
            "tolerable_error_rate": 5,
            "auditor_name": "Taku",
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert "Manual IDs" in response.get_json()["error"]


def test_mus_requires_positive_value_sampling_population(client):
    headers = auth_headers(client)
    engagement_id = create_engagement(client, headers)

    imported = client.post(
        f"/api/engagements/{engagement_id}/population",
        json=[
            {
                "transaction_ref": "TXN-ZERO-1",
                "account_code": "1000",
                "description": "Zero value row",
                "transaction_date": "2026-01-01",
                "amount": 0,
            },
            {
                "transaction_ref": "TXN-ZERO-2",
                "account_code": "2000",
                "description": "Another zero value row",
                "transaction_date": "2026-01-02",
                "amount": 0,
            },
        ],
        headers=headers,
    )
    assert imported.status_code == 201

    response = client.post(
        f"/api/engagements/{engagement_id}/run-sample",
        json={
            "sampling_method": "mus",
            "sample_size": 2,
            "materiality": 1000,
            "performance_materiality": 750,
            "clearly_trivial_threshold": 0,
            "confidence_level": 95,
            "expected_error_rate": 1,
            "tolerable_error_rate": 5,
            "auditor_name": "Taku",
            "random_seed": 7,
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert "positive-value item" in response.get_json()["error"]


def test_stratified_sampling_spreads_selection_across_strata():
    selected, strata_map = stratified_sampling(
        [
            {"id": 1, "amount": 520},
            {"id": 2, "amount": 430},
            {"id": 3, "amount": 180},
            {"id": 4, "amount": 140},
            {"id": 5, "amount": 60},
        ],
        sample_size=3,
        materiality=1000,
        seed=7,
    )
    assert len(selected) == 3
    assert len(set(selected)) == 3
    assert strata_map[1] == "high"
    assert strata_map[3] == "low"
    selected_strata = {strata_map[item_id] for item_id in selected}
    assert {"high", "medium", "low"}.issubset(selected_strata)


def test_mus_sampling_returns_unique_positive_value_hits():
    selected = mus_sampling(
        [
            {"id": 1, "amount": 1000},
            {"id": 2, "amount": 25},
            {"id": 3, "amount": 10},
        ],
        sample_size=2,
        seed=7,
    )
    assert len(selected) == 2
    assert len(set(selected)) == 2
    assert 1 in selected


def test_judgemental_sampling_deduplicates_manual_ids_in_order():
    assert judgemental_sampling([10, 11, 12], [11, 11, 12, 99]) == [11, 12]


def test_population_management_update_and_delete(client):
    headers = auth_headers(client)
    engagement_id = create_engagement(client, headers)

    rows = [
        {
            "transaction_ref": "TXN-EDIT-1",
            "account_code": "1100",
            "description": "Editable row",
            "transaction_date": "2026-02-01",
            "amount": 300,
        }
    ]

    import_response = client.post(
        f"/api/engagements/{engagement_id}/population",
        json=rows,
        headers=headers,
    )
    assert import_response.status_code == 201

    population = client.get(
        f"/api/engagements/{engagement_id}/population",
        headers=headers,
    )
    assert population.status_code == 200
    item_id = population.get_json()[0]["id"]

    update_response = client.put(
        f"/api/population/{item_id}",
        json={"description": "Updated row", "amount": 400},
        headers=headers,
    )
    assert update_response.status_code == 200
    updated = update_response.get_json()
    assert updated["description"] == "Updated row"
    assert float(updated["amount"]) == 400

    delete_response = client.delete(f"/api/population/{item_id}", headers=headers)
    assert delete_response.status_code == 200
    assert delete_response.get_json()["deleted"] is True


def test_audit_log_endpoint_has_sample_run_history(client):
    headers = auth_headers(client)
    engagement_id = create_engagement(client, headers)

    client.post(
        f"/api/engagements/{engagement_id}/population",
        json=[
            {
                "transaction_ref": "TXN-AUDIT-1",
                "account_code": "2000",
                "description": "Audit row",
                "transaction_date": "2026-03-01",
                "amount": 150,
            }
        ],
        headers=headers,
    )

    run = client.post(
        f"/api/engagements/{engagement_id}/run-sample",
        json={
            "sampling_method": "judgemental",
            "manual_ids": [],
            "sample_size": 0,
            "materiality": 1000,
            "confidence_level": 95,
            "expected_error_rate": 1,
            "tolerable_error_rate": 5,
            "auditor_name": "Taku",
        },
        headers=headers,
    )
    assert run.status_code == 201

    log = client.get(f"/api/engagements/{engagement_id}/audit-log", headers=headers)
    assert log.status_code == 200
    events = [row["event_type"] for row in log.get_json()]
    assert "sample_run_created" in events
