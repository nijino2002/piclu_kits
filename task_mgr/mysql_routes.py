import json
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta

from flask import jsonify, render_template, request, send_from_directory
from sqlalchemy import select
from werkzeug.utils import secure_filename

from config import RESULT_PACKAGE_DIR, TASK_PACKAGE_DIR, TEMP_DIR, ensure_storage_dirs
from database import session_scope
from models import Task, Worker
from repositories import (
    TERMINAL_STATUSES,
    VALID_STATUSES,
    add_event,
    task_events,
    update_task_status,
    upsert_worker,
)

WORKER_OFFLINE_TIMEOUT = timedelta(seconds=30)


def _read_task_config(package_path):
    try:
        with zipfile.ZipFile(package_path, "r") as archive:
            if "task_config.json" not in archive.namelist():
                return {}

            with archive.open("task_config.json") as file:
                return json.load(file)

    except (
        OSError,
        zipfile.BadZipFile,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return {}


def _worker_display_status(worker, now):
    if not worker.last_heartbeat_at:
        return "offline"

    if now - worker.last_heartbeat_at > WORKER_OFFLINE_TIMEOUT:
        return "offline"

    if worker.current_task_id:
        return "busy"

    return "online"

def _stored_path(directory, filename):
    if not filename or os.path.basename(filename) != filename:
        raise ValueError("Invalid stored filename")
    return directory / filename


def _event_log(events):
    lines = []
    for event in events:
        parts = [
            event.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            f"status={event.status}",
        ]
        if event.phase:
            parts.append(f"phase={event.phase}")
        if event.progress is not None:
            parts.append(f"progress={event.progress}")
        if event.worker_id:
            parts.append(f"worker={event.worker_id}")
        if event.message:
            parts.append(f"message={event.message}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _inject_dependency(task_path, result_path):
    with tempfile.TemporaryDirectory(dir=TEMP_DIR) as temporary:
        root = os.path.abspath(temporary)
        task_dir = os.path.join(root, "task")
        input_dir = os.path.join(root, "input")
        os.makedirs(task_dir)
        os.makedirs(input_dir)

        with zipfile.ZipFile(task_path) as archive:
            archive.extractall(task_dir)

        with zipfile.ZipFile(result_path) as archive:
            archive.extractall(input_dir)

        shutil.copytree(
            input_dir,
            os.path.join(task_dir, "input"),
            dirs_exist_ok=True,
        )

        temporary_zip = TEMP_DIR / f"{uuid.uuid4().hex}.zip"

        with zipfile.ZipFile(temporary_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for current_root, _, files in os.walk(task_dir):
                for filename in files:
                    source = os.path.join(current_root, filename)
                    archive.write(source, os.path.relpath(source, task_dir))

        os.replace(temporary_zip, task_path)


def install_mysql_routes(app, redis_client, api_base, high_queue, normal_queue):
    ensure_storage_dirs()

    def index():
        with session_scope() as session:
            records = session.scalars(
                select(Task).order_by(Task.submitted_at.desc())
            ).all()

            workers = session.scalars(select(Worker)).all()

            groups = {}

            for task in records:
                worker = task.worker_id or "Unassigned"
                has_result = bool(
                    task.result_package_path
                    and _stored_path(
                        RESULT_PACKAGE_DIR,
                        task.result_package_path,
                    ).exists()
                )

                groups.setdefault(worker, []).append({
                    "id": task.id,
                    "task_type": task.task_type,
                    "has_result": has_result,
                    "submit_time": task.submitted_at.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "finish_time": task.completed_at.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ) if task.completed_at else None,
                    "use_docker": task.use_docker,
                })

            for worker in workers:
                groups.setdefault(worker.id, [])

            now = datetime.utcnow()

            worker_statuses = {
                worker.id: {
                    "status": _worker_display_status(worker, now),
                    "ip_address": worker.ip_address,
                    "current_task_id": worker.current_task_id,
                    "last_heartbeat_at": (
                        worker.last_heartbeat_at.strftime("%Y-%m-%d %H:%M:%S")
                        if worker.last_heartbeat_at else None
                    ),
                }
                for worker in workers
            }

        return render_template(
            "index.html",
            ip_groups=groups,
            worker_statuses=worker_statuses,
        )

    def list_result_tasks():
        with session_scope() as session:
            records = session.scalars(
                select(Task).where(
                    Task.status == "success",
                    Task.result_package_path.is_not(None),
                )
            ).all()

            ids = [
                task.id
                for task in records
                if _stored_path(
                    RESULT_PACKAGE_DIR,
                    task.result_package_path,
                ).exists()
            ]

        return jsonify(ids)

    def start_task():
        uploaded = request.files.get("task_file")
        task_type = request.form.get("task_type", "").strip()
        dependency_id = request.form.get("dependency_id", "").strip() or None
        priority = request.form.get("priority", "normal").lower()

        if uploaded is None or not task_type:
            return jsonify({
                "status": "error",
                "message": "Missing task file or task type",
            }), 400

        if priority not in ("high", "normal"):
            priority = "normal"

        original_name = secure_filename(uploaded.filename or "")

        if not original_name.lower().endswith(".zip"):
            return jsonify({
                "status": "error",
                "message": "Task package must be a ZIP file",
            }), 400

        task_id = uuid.uuid4().hex
        package_name = f"{task_id}_task.zip"
        package_path = _stored_path(TASK_PACKAGE_DIR, package_name)

        try:
            uploaded.save(package_path)

            if not zipfile.is_zipfile(package_path):
                raise ValueError("Task package is not a valid ZIP file")
            
            task_config = _read_task_config(package_path)
            use_docker = bool(task_config.get("use_docker", True))
            with session_scope() as session:
                dependency = (
                    session.get(Task, dependency_id)
                    if dependency_id else None
                )

                if dependency_id and dependency is None:
                    raise ValueError("Dependency task does not exist")

                if dependency and not dependency.result_package_path:
                    raise ValueError("Dependency task has no result")

                if dependency:
                    dependency_path = _stored_path(
                        RESULT_PACKAGE_DIR,
                        dependency.result_package_path,
                    )

                    if not dependency_path.exists():
                        raise ValueError("Dependency result file is missing")

                    _inject_dependency(package_path, dependency_path)

                task = Task(
                    id=task_id,
                    task_type=task_type,
                    status="queued",
                    phase="queued",
                    progress=0,
                    priority=priority,
                    dependency_id=dependency_id,
                    task_package_path=package_name,
                    use_docker=use_docker,
                )

                session.add(task)

                add_event(
                    session,
                    task,
                    status="queued",
                    phase="queued",
                    progress=0,
                    message="Task submitted",
                )

            queue = high_queue if priority == "high" else normal_queue

            try:
                redis_client.lpush(queue, json.dumps({
                    "task_id": task_id,
                    "task_zip": package_name,
                    "task_type": task_type,
                    "priority": priority,
                }))
            except Exception as exc:
                with session_scope() as session:
                    task = session.get(Task, task_id)
                    update_task_status(
                        session,
                        task,
                        status="failed",
                        phase="queue_failed",
                        message=str(exc),
                    )

                return jsonify({
                    "status": "error",
                    "message": "Failed to queue task",
                }), 503

            return jsonify({
                "status": "success",
                "message": "Task queued",
                "task_id": task_id,
            })

        except ValueError as exc:
            package_path.unlink(missing_ok=True)
            return jsonify({
                "status": "error",
                "message": str(exc),
            }), 400

        except Exception as exc:
            package_path.unlink(missing_ok=True)
            app.logger.exception("Failed to start task")
            return jsonify({
                "status": "error",
                "message": str(exc),
            }), 500

    def task_status(task_id):
        with session_scope() as session:
            task = session.get(Task, task_id)

            if task is None:
                return jsonify({
                    "status": "error",
                    "message": "Task not found",
                }), 404

            events = task_events(session, task_id)

            has_result = bool(
                task.result_package_path
                and _stored_path(
                    RESULT_PACKAGE_DIR,
                    task.result_package_path,
                ).exists()
            )

            return jsonify({
                "status": task.status,
                "phase": task.phase,
                "progress": task.progress,
                "log": _event_log(events),
                "result": (
                    f"{api_base}/download_result/"
                    f"{task.result_package_path}"
                ) if has_result else None,
            })

    def report_status(task_id):
        data = request.get_json(silent=True) or {}

        with session_scope() as session:
            task = session.get(Task, task_id)

            if task is None:
                return jsonify({"error": "Task not found"}), 404

            phase = data.get("phase")
            status = data.get("status")

            if status is None:
                if phase == "completed_success":
                    status = "success"
                elif phase == "completed_failed":
                    status = "failed"
                elif phase == "cleanup" and task.status in TERMINAL_STATUSES:
                    status = task.status
                else:
                    status = "running"

            if status not in VALID_STATUSES:
                return jsonify({"error": "Invalid status"}), 400

            worker_id = data.get("worker_id")

            update_task_status(
                session,
                task,
                status=status,
                phase=phase,
                progress=data.get("progress"),
                message=data.get("msg"),
                worker_id=worker_id,
            )

            if worker_id:
                upsert_worker(
                    session,
                    worker_id,
                    hostname=data.get("hostname"),
                    ip_address=(
                        data.get("ip_address") or request.remote_addr
                    ),
                    current_task_id=(
                        None if status in TERMINAL_STATUSES else task_id
                    ),
                )

        return jsonify({"message": "Status updated"})

    def heartbeat():
        data = request.get_json(silent=True) or {}
        worker_id = data.get("worker_id")

        if not worker_id:
            return jsonify({"error": "worker_id is required"}), 400

        with session_scope() as session:
            upsert_worker(
                session,
                worker_id,
                hostname=data.get("hostname"),
                ip_address=data.get("ip_address") or request.remote_addr,
                current_task_id=data.get("current_task_id"),
            )

        return jsonify({"message": "Heartbeat updated"})

    def upload_result(filename):
        suffix = "_result.zip"

        if not filename.endswith(suffix):
            return jsonify({
                "status": "error",
                "message": "Invalid result filename",
            }), 400

        task_id = filename[:-len(suffix)]

        if len(task_id) != 32 or filename != f"{task_id}{suffix}":
            return jsonify({
                "status": "error",
                "message": "Invalid result filename",
            }), 400

        uploaded = request.files.get("file")

        if uploaded is None:
            return jsonify({
                "status": "error",
                "message": "Missing result file",
            }), 400

        temporary_path = TEMP_DIR / f"{uuid.uuid4().hex}.upload"
        result_path = _stored_path(RESULT_PACKAGE_DIR, filename)

        try:
            uploaded.save(temporary_path)

            if not zipfile.is_zipfile(temporary_path):
                raise ValueError("Result is not a valid ZIP file")

            with session_scope() as session:
                task = session.get(Task, task_id)

                if task is None:
                    return jsonify({
                        "status": "error",
                        "message": "Task not found",
                    }), 404

                os.replace(temporary_path, result_path)
                task.result_package_path = filename

                update_task_status(
                    session,
                    task,
                    status="success",
                    phase="completed_success",
                    progress=100,
                    message="Result uploaded successfully",
                    worker_id=task.worker_id,
                )

                if task.worker_id:
                    upsert_worker(
                        session,
                        task.worker_id,
                        current_task_id=None,
                    )

            return jsonify({
                "status": "success",
                "message": "Result uploaded successfully",
            })

        except ValueError as exc:
            return jsonify({
                "status": "error",
                "message": str(exc),
            }), 400

        finally:
            temporary_path.unlink(missing_ok=True)

    def download_result(filename):
        return send_from_directory(RESULT_PACKAGE_DIR, filename)

    def download_task(filename):
        return send_from_directory(TASK_PACKAGE_DIR, filename)

    app.view_functions["index"] = index
    app.view_functions["list_result_tasks"] = list_result_tasks
    app.view_functions["start_task"] = start_task
    app.view_functions["task_status"] = task_status
    app.view_functions["report_status"] = report_status
    app.view_functions["upload_result"] = upload_result
    app.view_functions["download_result"] = download_result
    app.view_functions["download_task"] = download_task

    app.add_url_rule(
        api_base + "/workers/heartbeat",
        endpoint="worker_heartbeat",
        view_func=heartbeat,
        methods=["POST"],
    )