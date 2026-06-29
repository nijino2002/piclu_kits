from datetime import datetime

from sqlalchemy import select

from models import Task, TaskEvent, Worker


TERMINAL_STATUSES = {"success", "failed"}
VALID_STATUSES = {"queued", "running", *TERMINAL_STATUSES}


def add_event(session, task, *, status=None, phase=None, progress=None, message=None, worker_id=None):
    event = TaskEvent(
        task_id=task.id,
        status=status or task.status,
        phase=phase,
        progress=progress,
        message=message,
        worker_id=worker_id,
    )
    session.add(event)
    return event


def update_task_status(
    session, task, *, status, phase=None, progress=None, message=None, worker_id=None
):
    now = datetime.utcnow()
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    task.status = status
    task.phase = phase
    if progress is not None:
        task.progress = max(0, min(100, int(progress)))
    if worker_id:
        task.worker_id = worker_id
    if status == "running" and task.started_at is None:
        task.started_at = now
    if status in TERMINAL_STATUSES:
        task.completed_at = now
    if status == "failed" and message:
        task.error_message = message
    task.updated_at = now
    add_event(
        session,
        task,
        status=status,
        phase=phase,
        progress=progress,
        message=message,
        worker_id=worker_id,
    )


def upsert_worker(
    session, worker_id, *, hostname=None, ip_address=None, current_task_id=None, status=None
):
    worker = session.get(Worker, worker_id)
    now = datetime.utcnow()
    if worker is None:
        worker = Worker(id=worker_id)
        session.add(worker)
    if hostname:
        worker.hostname = hostname
    if ip_address:
        worker.ip_address = ip_address
    worker.current_task_id = current_task_id
    worker.status = status or ("busy" if current_task_id else "online")
    worker.last_heartbeat_at = now
    worker.updated_at = now
    return worker


def task_events(session, task_id):
    return session.scalars(
        select(TaskEvent)
        .where(TaskEvent.task_id == task_id)
        .order_by(TaskEvent.created_at.asc(), TaskEvent.id.asc())
    ).all()
