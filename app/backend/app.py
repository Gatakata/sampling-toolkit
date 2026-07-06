import os
from functools import wraps
from math import floor, log10

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from db import (
    authenticate_user,
    create_user_session,
    create_admin_user,
    change_own_password,
    create_user,
    create_engagement,
    delete_population_item,
    delete_engagement,
    delete_sample_output_item,
    delete_user,
    delete_voided_audit_log_entries,
    clear_population,
    get_admin_status,
    get_user_by_token,
    get_users,
    get_audit_log,
    get_engagements,
    get_engagement,
    get_high_value_items,
    get_high_value_population_items,
    get_population_account_stats,
    get_population_item,
    get_population_items,
    get_population_all,
    get_population_summary,
    get_sample_output,
    get_sample_runs,
    save_population,
    set_user_password,
    create_sample_run,
    add_sample_output,
    update_own_profile,
    update_user_status,
    update_user,
    update_engagement,
    update_population_item,
    void_sample_run,
)
from sampling import (
    calculate_sample_size,
    random_sampling,
    systematic_sampling,
    mus_sampling,
    stratified_sampling,
    judgemental_sampling,
    build_sample_output,
)

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

BENCHMARK_RANGES = {
    "Revenue": (0.5, 3.0),
    "Income before tax": (3.0, 10.0),
    "Total Assets": (1.0, 2.0),
    "Gross revenue or expenditure": (0.5, 2.0),
}


def _extract_bearer_token(req):
    auth = req.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def professional_round(value):
    if value is None:
        return 0.0
    value = float(value)
    if value <= 0:
        return 0.0
    if value < 100:
        step = 1
    elif value < 1000:
        step = 10
    elif value < 10000:
        step = 100
    elif value < 100000:
        step = 500
    else:
        magnitude = 10 ** (max(int(floor(log10(value))) - 1, 1))
        step = magnitude
    return round(value / step) * step


def derive_materiality_thresholds(payload, existing=None):
    existing = existing or {}
    benchmark = payload.get("materiality_benchmark", existing.get("materiality_benchmark"))
    base = float(payload.get("materiality_base", existing.get("materiality_base") or 0) or 0)
    percent = float(payload.get("materiality_percent", existing.get("materiality_percent") or 0) or 0)

    calculated_overall = professional_round(base * (percent / 100.0)) if base > 0 and percent > 0 else 0.0
    overall = float(payload.get("materiality") or calculated_overall or existing.get("materiality") or 0)

    performance_percent = float(payload.get("performance_percent", existing.get("performance_percent") or 75) or 75)
    clearly_trivial_percent = float(payload.get("clearly_trivial_percent", existing.get("clearly_trivial_percent") or 3) or 3)

    calculated_pm = professional_round(overall * (performance_percent / 100.0))
    calculated_ct = professional_round(overall * (clearly_trivial_percent / 100.0))

    performance_materiality = float(payload.get("performance_materiality") or calculated_pm or existing.get("performance_materiality") or 0)
    clearly_trivial_threshold = float(payload.get("clearly_trivial_threshold") or calculated_ct or existing.get("clearly_trivial_threshold") or 0)

    return {
        "materiality_benchmark": benchmark,
        "materiality_base": base,
        "materiality_percent": percent,
        "materiality": overall,
        "performance_percent": performance_percent,
        "performance_materiality": performance_materiality,
        "clearly_trivial_percent": clearly_trivial_percent,
        "clearly_trivial_threshold": clearly_trivial_threshold,
    }


def validate_materiality_payload(model):
    benchmark = model.get("materiality_benchmark")
    if benchmark not in BENCHMARK_RANGES:
        return "Invalid materiality benchmark"

    base = float(model.get("materiality_base") or 0)
    percent = float(model.get("materiality_percent") or 0)
    overall = float(model.get("materiality") or 0)
    perf_percent = float(model.get("performance_percent") or 0)
    perf = float(model.get("performance_materiality") or 0)
    ct_percent = float(model.get("clearly_trivial_percent") or 0)
    ct = float(model.get("clearly_trivial_threshold") or 0)

    if base <= 0:
        return "Materiality base must be greater than zero"
    min_pct, max_pct = BENCHMARK_RANGES[benchmark]
    if percent < min_pct or percent > max_pct:
        return f"Materiality percent for {benchmark} must be between {min_pct}% and {max_pct}%"
    if overall <= 0:
        return "Overall materiality must be greater than zero"
    if perf_percent <= 0 or perf_percent > 100:
        return "Performance materiality percent must be between 0 and 100"
    if ct_percent <= 0 or ct_percent > 100:
        return "Clearly trivial percent must be between 0 and 100"
    if perf <= 0:
        return "Performance materiality must be greater than zero"
    if ct < 0:
        return "Clearly trivial threshold cannot be negative"
    if perf > overall:
        return "Performance materiality cannot exceed overall materiality"
    if ct > perf:
        return "Clearly trivial threshold cannot exceed performance materiality"
    return None


def parse_positive_float(value, field_name, allow_zero=False):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None, f"{field_name} must be numeric"
    if allow_zero:
        if num < 0:
            return None, f"{field_name} cannot be negative"
    elif num <= 0:
        return None, f"{field_name} must be greater than zero"
    return num, None


def require_admin(handler):
    @wraps(handler)
    def wrapper(*args, **kwargs):
        token = _extract_bearer_token(request)
        user = get_user_by_token(token)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401
        if not bool(user.get("is_active", 1)):
            return jsonify({"error": "User account disabled"}), 403
        if not bool(user.get("is_admin")):
            return jsonify({"error": "Admin privileges required"}), 403
        request.current_user = user
        return handler(*args, **kwargs)

    return wrapper


def require_auth(handler):
    @wraps(handler)
    def wrapper(*args, **kwargs):
        token = _extract_bearer_token(request)
        user = get_user_by_token(token)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401
        if not bool(user.get("is_active", 1)):
            return jsonify({"error": "User account disabled"}), 403
        request.current_user = user
        return handler(*args, **kwargs)

    return wrapper


@app.route("/", methods=["GET"])
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/admin/status", methods=["GET"])
def admin_status():
    return jsonify(get_admin_status())


@app.route("/api/admin/setup", methods=["POST"])
@require_admin
def admin_setup():
    payload = request.get_json() or {}
    payload["is_admin"] = True
    payload["created_by"] = request.current_user["id"]
    payload.setdefault("first_name", (payload.get("username") or "Admin").split()[0])
    payload.setdefault("surname", "Admin")
    result = create_admin_user(payload)
    if result.get("created"):
        return jsonify(result), 201
    return jsonify({"error": result.get("message", "Unable to create admin")}), 400


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    payload = request.get_json() or {}
    auth_result = authenticate_user(payload.get("username"), payload.get("password"))
    if auth_result.get("ok"):
        user = auth_result["user"]
        session = create_user_session(user["id"])
        return jsonify({"ok": True, "user": user, "token": session["token"], "expires_at": session["expires_at"]})

    code = auth_result.get("code")
    if code == "ACCOUNT_LOCKED":
        return jsonify({"error": auth_result.get("error"), "code": code, "locked_until": auth_result.get("locked_until")}), 423
    if code == "ACCOUNT_DISABLED":
        return jsonify({"error": auth_result.get("error"), "code": code}), 403
    return jsonify({"error": auth_result.get("error", "Invalid credentials"), "code": code}), 401


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    return admin_login()


@app.route("/api/auth/me", methods=["GET"])
@require_auth
def auth_me():
    token = _extract_bearer_token(request)
    user = get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(user)


@app.route("/api/auth/change-password", methods=["POST"])
def auth_change_password():
    token = _extract_bearer_token(request)
    user = get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    payload = request.get_json() or {}
    result = change_own_password(
        user["id"],
        payload.get("current_password"),
        payload.get("new_password"),
    )
    if not result.get("updated"):
        return jsonify({"error": result.get("message", "Unable to update password")}), 400
    return jsonify({"updated": True})


@app.route("/api/users", methods=["GET"])
@require_admin
def users_list():
    return jsonify(get_users())


@app.route("/api/users", methods=["POST"])
@require_admin
def users_create():
    payload = request.get_json() or {}
    result = create_user(payload, request.current_user["id"])
    if result.get("created"):
        return jsonify(result), 201
    if result.get("errors"):
        return jsonify({"success": False, "errors": result["errors"], "error": "Unable to create user"}), 400
    return jsonify({"error": result.get("message", "Unable to create user")}), 400


@app.route("/api/users/<int:user_id>", methods=["PATCH"])
@require_admin
def users_update(user_id):
    payload = request.get_json() or {}
    if request.current_user["id"] == user_id and payload.get("is_admin") is False:
        return jsonify({"error": "Admins cannot remove their own admin privileges"}), 400
    result = update_user(user_id, payload, acted_by=request.current_user.get("username"))
    if not result.get("updated"):
        if result.get("errors"):
            return jsonify({"success": False, "errors": result["errors"], "error": "Unable to update user"}), 400
        return jsonify({"error": result.get("message", "Unable to update user")}), 400
    return jsonify(result["user"])


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@require_admin
def users_delete(user_id):
    if request.current_user["id"] == user_id:
        return jsonify({"error": "Admins cannot delete their own account"}), 400
    result = delete_user(user_id, acted_by=request.current_user.get("username"))
    if not result.get("deleted"):
        return jsonify({"error": result.get("message", "Unable to delete user")}), 404
    return jsonify(result)


@app.route("/api/users/<int:user_id>/status", methods=["PATCH"])
@require_admin
def user_status_update(user_id):
    payload = request.get_json() or {}
    is_active = bool(payload.get("is_active", True))
    if request.current_user["id"] == user_id and not is_active:
        return jsonify({"error": "Admins cannot disable their own account"}), 400
    updated = update_user_status(user_id, is_active, acted_by=request.current_user.get("username"))
    if not updated:
        return jsonify({"error": "User not found"}), 404
    return jsonify(updated)


@app.route("/api/users/<int:user_id>/password", methods=["PATCH"])
@require_admin
def user_password_admin_reset(user_id):
    payload = request.get_json() or {}
    new_password = payload.get("new_password")
    force_reset = bool(payload.get("must_reset_password", True))
    result = set_user_password(
        user_id,
        new_password,
        must_reset_password=force_reset,
        acted_by=request.current_user.get("username"),
    )
    if not result.get("updated"):
        return jsonify({"error": result.get("message", "Unable to set password")}), 400
    return jsonify({"updated": True})


@app.route("/api/auth/profile", methods=["PUT"])
@require_auth
def auth_profile_update():
    payload = request.get_json() or {}
    result = update_own_profile(request.current_user["id"], payload)
    if not result.get("updated"):
        if result.get("errors"):
            return jsonify({"success": False, "errors": result["errors"], "error": "Unable to update profile"}), 400
        return jsonify({"error": result.get("message", "Unable to update profile")}), 400
    return jsonify(result["user"])


@app.route("/api/engagements", methods=["POST"])
@require_admin
def create_engagement_route():
    data = request.get_json() or {}
    thresholds = derive_materiality_thresholds(data)
    data.update(thresholds)
    validation_error = validate_materiality_payload(data)
    if validation_error:
        return jsonify({"error": validation_error}), 400
    data["created_by"] = request.current_user.get("username")
    engagement = create_engagement(data, acted_by=request.current_user.get("username"))
    return jsonify(engagement), 201


@app.route("/api/engagements", methods=["GET"])
@require_auth
def list_engagements():
    return jsonify(get_engagements())


@app.route("/api/engagements/<int:engagement_id>", methods=["GET"])
@require_auth
def engagement_details(engagement_id):
    engagement = get_engagement(engagement_id)
    if not engagement:
        return jsonify({"error": "Engagement not found"}), 404
    return jsonify(engagement)


@app.route("/api/engagements/<int:engagement_id>", methods=["PUT"])
@require_admin
def update_engagement_route(engagement_id):
    payload = request.get_json() or {}
    existing = get_engagement(engagement_id)
    if not existing:
        return jsonify({"error": "Engagement not found"}), 404
    merged = {
        "client_name": payload.get("client_name", existing.get("client_name")),
        "engagement_ref": payload.get("engagement_ref", existing.get("engagement_ref")),
        "auditor_name": payload.get("auditor_name", existing.get("auditor_name")),
        "financial_year": payload.get("financial_year", existing.get("financial_year")),
        "materiality_benchmark": payload.get("materiality_benchmark", existing.get("materiality_benchmark")),
        "materiality_base": payload.get("materiality_base", existing.get("materiality_base")),
        "materiality_percent": payload.get("materiality_percent", existing.get("materiality_percent")),
        "materiality": payload.get("materiality", existing.get("materiality")),
        "performance_percent": payload.get("performance_percent", existing.get("performance_percent")),
        "performance_materiality": payload.get("performance_materiality", existing.get("performance_materiality")),
        "clearly_trivial_percent": payload.get("clearly_trivial_percent", existing.get("clearly_trivial_percent")),
        "clearly_trivial_threshold": payload.get("clearly_trivial_threshold", existing.get("clearly_trivial_threshold")),
    }
    merged.update(derive_materiality_thresholds(merged, existing=existing))
    validation_error = validate_materiality_payload(merged)
    if validation_error:
        return jsonify({"error": validation_error}), 400
    updated = update_engagement(engagement_id, merged, acted_by=request.current_user.get("username"))
    return jsonify(updated)


@app.route("/api/engagements/<int:engagement_id>", methods=["DELETE"])
@require_admin
def delete_engagement_route(engagement_id):
    result = delete_engagement(engagement_id, acted_by=request.current_user.get("username"))
    if not result.get("deleted"):
        return jsonify({"error": result.get("message", "Unable to delete engagement")}), 404
    return jsonify(result)


@app.route("/api/admin/engagements", methods=["GET"])
@require_admin
def admin_list_engagements():
    return jsonify(get_engagements())


@app.route("/api/engagements/<int:engagement_id>/population", methods=["POST"])
@require_admin
def upload_population(engagement_id):
    rows = request.get_json() or []
    if not isinstance(rows, list):
        return jsonify({"error": "Population payload must be an array of rows"}), 400
    if len(rows) == 0:
        return jsonify({"error": "Population payload is empty"}), 400
    if len(rows) > 100000:
        return jsonify({"error": "Population payload too large"}), 400
    parsed_rows = []
    for idx, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            return jsonify({"error": f"Population row {idx} is invalid"}), 400
        amount, error = parse_positive_float(row.get("amount"), f"amount on row {idx}", allow_zero=True)
        if error:
            return jsonify({"error": error}), 400
        if not (row.get("transaction_ref") or "").strip():
            return jsonify({"error": f"transaction_ref is required on row {idx}"}), 400
        parsed_rows.append({
            "account_code": row.get("account_code"),
            "transaction_ref": row.get("transaction_ref"),
            "description": row.get("description"),
            "transaction_date": row.get("transaction_date"),
            "amount": amount,
            "is_high_value": False,
        })
    import_result = save_population(engagement_id, parsed_rows, acted_by=request.current_user.get("username"))
    summary = get_population_summary(engagement_id)
    return jsonify({"summary": summary, "duplicates": import_result["duplicates"], "inserted": import_result["inserted"]}), 201


@app.route("/api/engagements/<int:engagement_id>/population", methods=["GET"])
@require_auth
def list_population(engagement_id):
    account_code = request.args.get("account_code")
    performance_materiality = request.args.get("performance_materiality", type=float, default=0)
    clearly_trivial_threshold = request.args.get("clearly_trivial_threshold", type=float, default=0)
    include_high_value = request.args.get("include_high_value", default="true").lower() != "false"
    include_trivial = request.args.get("include_trivial", default="true").lower() != "false"
    items = get_population_items(
        engagement_id,
        account_code=account_code,
        performance_materiality=performance_materiality,
        clearly_trivial_threshold=clearly_trivial_threshold,
        include_high_value=include_high_value,
        include_trivial=include_trivial,
    )
    return jsonify(items)


@app.route("/api/admin/population", methods=["GET"])
@require_admin
def admin_list_population_all():
    account_code = request.args.get("account_code")
    return jsonify(get_population_all(account_code=account_code))


@app.route("/api/population/<int:item_id>", methods=["GET"])
@require_auth
def population_item_details(item_id):
    item = get_population_item(item_id)
    if not item:
        return jsonify({"error": "Population item not found"}), 404
    return jsonify(item)


@app.route("/api/population/<int:item_id>", methods=["PUT"])
@require_admin
def population_item_update(item_id):
    payload = request.get_json() or {}
    existing = get_population_item(item_id)
    if not existing:
        return jsonify({"error": "Population item not found"}), 404
    merged = {
        "account_code": payload.get("account_code", existing.get("account_code")),
        "transaction_ref": payload.get("transaction_ref", existing.get("transaction_ref")),
        "description": payload.get("description", existing.get("description")),
        "transaction_date": payload.get("transaction_date", existing.get("transaction_date")),
        "amount": payload.get("amount", existing.get("amount")),
    }
    amount, error = parse_positive_float(merged.get("amount"), "amount", allow_zero=True)
    if error:
        return jsonify({"error": error}), 400
    merged["amount"] = amount
    updated = update_population_item(item_id, merged, acted_by=request.current_user.get("username"))
    return jsonify(updated)


@app.route("/api/population/<int:item_id>", methods=["DELETE"])
@require_admin
def population_item_delete(item_id):
    existing = get_population_item(item_id)
    if not existing:
        return jsonify({"error": "Population item not found"}), 404
    return jsonify(delete_population_item(item_id, acted_by=request.current_user.get("username")))


@app.route("/api/engagements/<int:engagement_id>/population", methods=["DELETE"])
@require_admin
def population_clear(engagement_id):
    engagement = get_engagement(engagement_id)
    if not engagement:
        return jsonify({"error": "Engagement not found"}), 404
    return jsonify(clear_population(engagement_id, acted_by=request.current_user.get("username")))


@app.route("/api/engagements/<int:engagement_id>/population/summary", methods=["GET"])
@require_auth
def population_summary(engagement_id):
    perf = request.args.get("performance_materiality", type=float)
    trivial = request.args.get("clearly_trivial_threshold", type=float)
    if perf is None or trivial is None:
        engagement = get_engagement(engagement_id)
        if not engagement:
            return jsonify({"error": "Engagement not found"}), 404
        perf = float(perf if perf is not None else (engagement.get("performance_materiality") or 0))
        trivial = float(trivial if trivial is not None else (engagement.get("clearly_trivial_threshold") or 0))
    summary = get_population_summary(engagement_id, perf, trivial)
    return jsonify(summary)


@app.route("/api/engagements/<int:engagement_id>/population/accounts", methods=["GET"])
@require_auth
def population_account_stats(engagement_id):
    perf = request.args.get("performance_materiality", type=float, default=0)
    trivial = request.args.get("clearly_trivial_threshold", type=float, default=0)
    return jsonify(get_population_account_stats(engagement_id, perf, trivial))


@app.route("/api/engagements/<int:engagement_id>/high-value", methods=["GET"])
@require_auth
def high_value_population(engagement_id):
    performance_materiality = request.args.get("performance_materiality", type=float, default=0)
    return jsonify(get_high_value_population_items(engagement_id, performance_materiality))


@app.route("/api/sample-size/calculate", methods=["GET"])
@require_auth
def calculate_sample_size_route():
    confidence_level = request.args.get("confidence_level", type=float, default=95)
    expected_error_rate = request.args.get("expected_error_rate", type=float, default=0.5)
    tolerable_error_rate = request.args.get("tolerable_error_rate", type=float)
    performance_materiality = request.args.get("performance_materiality", type=float)
    population_value = request.args.get("population_value", type=float)
    population_size = request.args.get("population_size", type=int, default=0)
    if confidence_level not in {90.0, 95.0, 99.0}:
        return jsonify({"error": "Confidence level must be 90, 95, or 99"}), 400
    if expected_error_rate < 0 or expected_error_rate > 100:
        return jsonify({"error": "Expected error rate must be between 0 and 100"}), 400
    if population_size < 0:
        return jsonify({"error": "Population size cannot be negative"}), 400
    if tolerable_error_rate is not None and (tolerable_error_rate <= 0 or tolerable_error_rate > 100):
        return jsonify({"error": "Tolerable error rate must be between 0 and 100"}), 400
    if performance_materiality is not None and performance_materiality <= 0:
        return jsonify({"error": "Performance materiality must be greater than zero"}), 400
    if population_value is not None and population_value <= 0:
        return jsonify({"error": "Population value must be greater than zero"}), 400
    size = calculate_sample_size(
        confidence_level,
        expected_error_rate,
        population_size,
        tolerable_error_rate=tolerable_error_rate,
        tolerable_misstatement=performance_materiality,
        population_value=population_value,
    )
    return jsonify({"recommended_sample_size": size})


@app.route("/api/engagements/<int:engagement_id>/run-sample", methods=["POST"])
@require_admin
def run_sample(engagement_id):
    payload = request.get_json() or {}
    engagement = get_engagement(engagement_id)
    if not engagement:
        return jsonify({"error": "Engagement not found"}), 404
    population_items = get_population_items(engagement_id)
    if not population_items:
        return jsonify({"error": "Population is empty"}), 400
    sample_size = int(payload.get("sample_size", 0))
    confidence_level = float(payload.get("confidence_level", 95))
    expected_error_rate = float(payload.get("expected_error_rate", 0.5))
    tolerable_error_rate = float(payload.get("tolerable_error_rate", 0) or 0)
    if tolerable_error_rate <= 0:
        # Keep run-sample resilient when UI-derived tolerable rate is zero.
        tolerable_error_rate = 5.0
    elif tolerable_error_rate > 100:
        # Derived tolerable rates can exceed 100 for tiny populations; cap instead of failing the run.
        tolerable_error_rate = 100.0
    overall_materiality = float(payload.get("materiality", engagement.get("materiality") or 0))
    performance_materiality = float(payload.get("performance_materiality", engagement.get("performance_materiality") or 0))
    clearly_trivial_threshold = float(payload.get("clearly_trivial_threshold", engagement.get("clearly_trivial_threshold") or 0))
    method = payload.get("sampling_method", "random")
    seed = payload.get("random_seed")
    manual_ids = payload.get("manual_ids", [])

    if method not in {"random", "systematic", "mus", "stratified", "judgemental"}:
        return jsonify({"error": "Unsupported sampling method"}), 400
    if confidence_level not in {90.0, 95.0, 99.0}:
        return jsonify({"error": "Confidence level must be 90, 95, or 99"}), 400
    if expected_error_rate < 0 or expected_error_rate > 100:
        return jsonify({"error": "Expected error rate must be between 0 and 100"}), 400
    if performance_materiality <= 0:
        return jsonify({"error": "Performance materiality must be greater than zero"}), 400
    if clearly_trivial_threshold < 0:
        return jsonify({"error": "Clearly trivial threshold cannot be negative"}), 400
    if clearly_trivial_threshold > performance_materiality:
        return jsonify({"error": "Clearly trivial threshold cannot exceed performance materiality"}), 400

    high_value_items = get_high_value_population_items(engagement_id, performance_materiality)
    high_value_ids = [item["id"] for item in high_value_items]
    eligible_items = [
        item
        for item in population_items
        if item["id"] not in high_value_ids and (item.get("amount") or 0) >= clearly_trivial_threshold
    ]
    eligible_ids = [item["id"] for item in eligible_items]

    if sample_size <= 0:
        sample_size = calculate_sample_size(
            confidence_level,
            expected_error_rate,
            len(eligible_items),
            tolerable_error_rate=tolerable_error_rate,
            tolerable_misstatement=performance_materiality,
            population_value=sum((item.get("amount") or 0) for item in eligible_items),
        )
    if sample_size > len(eligible_items):
        sample_size = len(eligible_items)
    if sample_size < 0:
        return jsonify({"error": "Sample size cannot be negative"}), 400
    if method == "judgemental" and not manual_ids:
        return jsonify({"error": "Manual IDs are required for judgemental sampling"}), 400
    if method == "mus" and not any((item.get("amount") or 0) > 0 for item in eligible_items):
        return jsonify({"error": "MUS requires at least one positive-value item in the sampling population"}), 400

    population_ids = [item["id"] for item in population_items]
    selected_ids = []
    strata_map = {}
    if method == "random":
        selected_ids = random_sampling(eligible_ids, sample_size, seed)
    elif method == "systematic":
        selected_ids = systematic_sampling(eligible_ids, sample_size, seed)
    elif method == "mus":
        selected_ids = mus_sampling(eligible_items, sample_size, seed)
    elif method == "stratified":
        selected_ids, strata_map = stratified_sampling(eligible_items, sample_size, performance_materiality, seed)
    elif method == "judgemental":
        selected_ids = judgemental_sampling(population_ids, manual_ids)

    sample_size = len(selected_ids)


    outputs = build_sample_output(
        population_items,
        selected_ids,
        performance_materiality,
        clearly_trivial_threshold,
        auto_high_value_ids=high_value_ids,
        strata_map=strata_map,
    )
    high_value_count = sum(1 for item in outputs if item["is_high_value"])
    run_payload = {
        "engagement_id": engagement_id,
        "auditor_name": payload.get("auditor_name", engagement.get("auditor_name")),
        "sampling_method": method,
        "population_count": len(population_items),
        "population_value": sum(item["amount"] for item in population_items),
        "materiality": overall_materiality,
        "performance_materiality": performance_materiality,
        "clearly_trivial_threshold": clearly_trivial_threshold,
        "confidence_level": confidence_level,
        "expected_error_rate": expected_error_rate,
        "tolerable_error_rate": tolerable_error_rate,
        "sample_size": sample_size,
        "random_seed": seed,
        "high_value_count": high_value_count,
        "notes": payload.get("notes"),
    }
    run = create_sample_run(run_payload)
    add_sample_output(run["id"], outputs)
    return jsonify({"run": run, "output_count": len(outputs)}), 201


@app.route("/api/engagements/<int:engagement_id>/runs", methods=["GET"])
@require_auth
def list_runs(engagement_id):
    return jsonify(get_sample_runs(engagement_id))


@app.route("/api/audit-log", methods=["GET"])
@require_auth
def all_audit_log():
    user_name = request.args.get("user")
    method = request.args.get("method")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    is_voided = request.args.get("voided")
    voided_filter = None
    if is_voided is not None:
        voided_filter = str(is_voided).lower() in {"1", "true", "yes"}
    return jsonify(get_audit_log(user_name=user_name, method=method, from_date=from_date, to_date=to_date, is_voided=voided_filter))


@app.route("/api/engagements/<int:engagement_id>/audit-log", methods=["GET"])
@require_auth
def engagement_audit_log(engagement_id):
    user_name = request.args.get("user")
    method = request.args.get("method")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    is_voided = request.args.get("voided")
    voided_filter = None
    if is_voided is not None:
        voided_filter = str(is_voided).lower() in {"1", "true", "yes"}
    return jsonify(
        get_audit_log(
            engagement_id=engagement_id,
            user_name=user_name,
            method=method,
            from_date=from_date,
            to_date=to_date,
            is_voided=voided_filter,
        )
    )


@app.route("/api/audit-log/voided", methods=["DELETE"])
@require_admin
def delete_voided_audit_log():
    return jsonify(delete_voided_audit_log_entries(acted_by=request.current_user.get("username")))


@app.route("/api/runs/<int:run_id>/output", methods=["GET"])
@require_auth
def run_output(run_id):
    return jsonify(get_sample_output(run_id))


@app.route("/api/runs/<int:run_id>/high-value", methods=["GET"])
@require_auth
def run_high_value(run_id):
    return jsonify(get_high_value_items(run_id))


@app.route("/api/sample-output/<int:output_id>", methods=["DELETE"])
@require_admin
def sample_output_delete(output_id):
    result = delete_sample_output_item(output_id, acted_by=request.current_user.get("username"))
    if not result.get("deleted"):
        return jsonify({"error": result.get("message", "Unable to delete sample record")}), 404
    return jsonify(result)


@app.route("/api/runs/<int:run_id>/void", methods=["POST"])
@require_admin
def sample_run_void(run_id):
    result = void_sample_run(run_id, acted_by=request.current_user.get("username"))
    if not result.get("voided"):
        return jsonify({"error": result.get("message", "Unable to void sample run")}), 400
    return jsonify(result)


@app.route("/static/<path:path>", methods=["GET"])
def static_proxy(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
