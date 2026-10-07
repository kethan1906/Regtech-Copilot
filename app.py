from flask import Flask, Response, g, jsonify, render_template, request
import tempfile

import config
from database.db import get_connection
from services.report_service import build_summary, flagged_csv
from services.monitoring_service import run_monitoring
from scripts.import_data import import_transactions
from services.transaction_service import VALID_RISK_LEVELS, list_transactions


class BadRequest(ValueError):
    pass


def _int_arg(name: str, default: int, minimum: int, maximum: int | None = None) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise BadRequest(f"'{name}' must be an integer") from None
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"between {minimum} and {maximum}" if maximum else f">= {minimum}"
        raise BadRequest(f"'{name}' must be {bound}")
    return value


def _risk_arg() -> str | None:
    raw = request.args.get("risk_level")
    if raw is None or raw == "":
        return None
    value = raw.upper()
    if value not in VALID_RISK_LEVELS:
        raise BadRequest(f"'risk_level' must be one of {', '.join(VALID_RISK_LEVELS)}")
    return value


def _bool_arg(name: str) -> bool:
    return request.args.get(name, "false").lower() in {"1", "true", "yes"}


def create_app(database_path=None) -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = str(database_path or config.DATABASE_PATH)
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

    def db():
        if "db" not in g:
            g.db = get_connection(app.config["DATABASE_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.errorhandler(BadRequest)
    def handle_bad_request(exc):
        return jsonify({"error": str(exc)}), 400

    @app.errorhandler(404)
    def handle_404(_exc):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(413)
    def handle_too_large(_exc):
        return jsonify({"error": "CSV file is too large (maximum 50 MB)"}), 413

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/health")
    def health():
        db().execute("SELECT 1")
        return jsonify({"status": "ok"})

    @app.route("/api/transactions", methods=["GET"])
    def transactions():
        return jsonify(
            list_transactions(
                db(),
                limit=_int_arg("limit", config.DEFAULT_PAGE_SIZE, 1, config.MAX_PAGE_SIZE),
                offset=_int_arg("offset", 0, 0),
                risk_level=_risk_arg(),
                flagged_only=_bool_arg("flagged_only"),
            )
        )

    @app.route("/api/alerts", methods=["GET"])
    def alerts():
        risk = _risk_arg()
        if risk == "LOW":
            raise BadRequest("alerts only exist for MEDIUM and HIGH risk")
        return jsonify(
            list_transactions(
                db(),
                limit=_int_arg("limit", config.DEFAULT_PAGE_SIZE, 1, config.MAX_PAGE_SIZE),
                offset=_int_arg("offset", 0, 0),
                risk_level=risk,
                flagged_only=True,
            )
        )

    @app.route("/api/import", methods=["POST"])
    def import_csv():
        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename:
            raise BadRequest("Please choose a CSV file to upload")
        if not uploaded.filename.lower().endswith(".csv"):
            raise BadRequest("Only CSV files are supported")

        replace = request.form.get("replace", "false").lower() in {"1", "true", "yes", "on"}
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                temp_path = tmp.name
                uploaded.save(tmp)
            imported = import_transactions(db(), temp_path, replace=replace)
            monitoring = run_monitoring(db())
            return jsonify({
                "status": "ok",
                "imported_transactions": imported,
                "replaced_existing_data": replace,
                "monitoring": monitoring,
            })
        except (ValueError, OSError) as exc:
            db().rollback()
            raise BadRequest(f"Import failed: {exc}") from None
        finally:
            if temp_path:
                try:
                    import os
                    os.remove(temp_path)
                except OSError:
                    pass

    @app.route("/api/reports/summary", methods=["GET"])
    def report_summary():
        return jsonify(build_summary(db()))

    @app.route("/api/reports/flagged.csv", methods=["GET"])
    def report_csv():
        risk = _risk_arg()
        if risk == "LOW":
            raise BadRequest("the report only contains MEDIUM and HIGH risk transactions")
        return Response(
            flagged_csv(db(), risk),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=flagged_transactions.csv"},
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=config.FLASK_DEBUG)
