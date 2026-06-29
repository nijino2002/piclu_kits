import json
import logging
import os
import shutil
import shutil as sh
import subprocess
import time
import socket
import zipfile
import threading
from pathlib import Path

import redis
import requests

TASK_ZIP_DIR = "/home/pi/tasks"
WORK_BASE_DIR = "/home/pi/task_manager/work"
RESULT_DIR = "/home/pi/task_manager/results"
LOG_FILE_PATH = "/home/pi/task_manager/client.log"

SERVER_URL = "http://192.168.12.201:5000"
API_BASE = "/pi_task"

REDIS_HOST = "192.168.12.201"
REDIS_PORT = 6379
TASK_QUEUE_HIGH = "pi_task_high"
TASK_QUEUE_NORMAL = "pi_task_normal"
WORKER_ID = socket.gethostname()
PROCESSING_QUEUE_HIGH = f"pi_task_high_processing_{WORKER_ID}"
PROCESSING_QUEUE_NORMAL = f"pi_task_normal_processing_{WORKER_ID}"

CURRENT_TASK_ID = None
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "10"))

BASE_IMAGE_CANDIDATES = [
    "python:3.11-slim-bookworm",
    "dockerproxy.net/library/python:3.11-slim-bookworm",
]
DEFAULT_PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"

os.makedirs(TASK_ZIP_DIR, exist_ok=True)
os.makedirs(WORK_BASE_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.FileHandler(LOG_FILE_PATH), logging.StreamHandler()],
)
logger = logging.getLogger("client")
rds = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)


def log(msg):
    logger.info(msg)


def report(task_id, phase=None, msg=None, progress=None, status=None):
    payload = {
        "worker_id": WORKER_ID,
        "hostname": socket.gethostname(),
        "ip_address": _worker_ip(),
    }
    if phase is not None:
        payload["phase"] = phase
    if msg is not None:
        payload["msg"] = msg
    if progress is not None:
        payload["progress"] = progress
    if status is not None:
        payload["status"] = status

    try:
        resp = requests.post(
            f"{SERVER_URL}{API_BASE}/report_status/{task_id}",
            json=payload,
            timeout=5,
        )
        log(f"Report status ({phase}): {resp.status_code}")
    except Exception as exc:
        log(f"Report status failed: {exc}")

def _worker_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


def heartbeat_loop():
    while True:
        try:
            requests.post(
                f"{SERVER_URL}{API_BASE}/workers/heartbeat",
                json={
                    "worker_id": WORKER_ID,
                    "hostname": socket.gethostname(),
                    "ip_address": _worker_ip(),
                    "current_task_id": CURRENT_TASK_ID,
                },
                timeout=5,
            )
        except Exception as exc:
            log(f"Heartbeat failed: {exc}")
        time.sleep(HEARTBEAT_INTERVAL)

def load_task_config(task_dir):
    config_path = os.path.join(task_dir, "task_config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log(f"Failed to load config: {exc}. Defaulting to use_docker=True")
        return {"use_docker": True}


def upload_result(task_id, result_zip_path):
    try:
        with open(result_zip_path, "rb") as f:
            resp = requests.post(
                f"{SERVER_URL}{API_BASE}/upload_result/{task_id}_result.zip",
                files={"file": f},
                timeout=60,
            )
        log(f"Upload response: {resp.status_code} - {resp.text}")
        return 200 <= resp.status_code < 300
    except Exception as exc:
        log(f"Failed to upload result: {exc}")
        return False


def run_native_task(task_id, task_dir):
    report(task_id, phase="container_started", msg="Starting native run", progress=45, status="running")
    try:
        req_file = os.path.join(task_dir, "requirements.txt")
        if os.path.exists(req_file):
            report(task_id, phase="running", msg="Installing requirements (native)", progress=50, status="running")
            subprocess.run(["pip3", "install", "-r", req_file], check=False)

        main_file = os.path.join(task_dir, "main.py")
        report(task_id, phase="running", msg="Executing main.py (native)", progress=60, status="running")
        result = subprocess.run(
            ["python3", main_file],
            cwd=task_dir,
            capture_output=True,
            text=True,
        )
        log(f"NATIVE STDOUT:\n{result.stdout}")
        log(f"NATIVE STDERR:\n{result.stderr}")

        if result.returncode != 0:
            report(task_id, phase="completed_failed", msg=f"Native run exitcode={result.returncode}", status="failed")
            return False
        return True
    except Exception as exc:
        log(f"Exception during native execution: {exc}")
        report(task_id, phase="completed_failed", msg=str(exc), status="failed")
        return False


def _resolve_docker_path():
    for path in ("/usr/bin/docker", "/usr/local/bin/docker"):
        if os.path.exists(path):
            return path
    return sh.which("docker")


def _docker_env():
    env = os.environ.copy()
    env["DOCKER_BUILDKIT"] = "1"
    for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _docker_pull_with_retry(docker_cmd, image, retries=3, sleep_sec=3):
    for attempt in range(1, retries + 1):
        pull = subprocess.run(
            [docker_cmd, "pull", image],
            capture_output=True,
            text=True,
            env=_docker_env(),
        )
        if pull.returncode == 0:
            return True
        tail = pull.stderr.strip().splitlines()[-10:]
        log("DOCKER PULL BASE STDERR (tail):\n" + "\n".join(tail))
        time.sleep(sleep_sec * attempt)
    return False


def _select_base_image(docker_cmd):
    for base in BASE_IMAGE_CANDIDATES:
        if _docker_pull_with_retry(docker_cmd, base):
            return base
    return None


def run_docker_task(task_id, task_dir):
    docker_cmd = _resolve_docker_path()
    if not docker_cmd:
        msg = "Docker command not found in PATH"
        log(msg)
        report(task_id, phase="completed_failed", msg=msg, status="failed")
        return False

    base_image = _select_base_image(docker_cmd)
    if not base_image:
        msg = "Failed to pull any base image candidates"
        log(msg)
        report(task_id, phase="completed_failed", msg=msg, status="failed")
        return False

    docker_image = f"task_image_{task_id}"

    try:
        report(task_id, phase="image_build", msg=f"Building Docker image from {base_image}", progress=20, status="running")
        build_cmd = [
            docker_cmd,
            "build",
            "--pull",
            "--build-arg",
            f"BASE_IMAGE={base_image}",
            "--build-arg",
            f"PIP_INDEX_URL={DEFAULT_PYPI_MIRROR}",
            "-t",
            docker_image,
            ".",
        ]

        build = subprocess.run(
            build_cmd,
            cwd=task_dir,
            capture_output=True,
            text=True,
            env=_docker_env(),
        )
        if build.returncode != 0:
            tail = (build.stderr or "").strip().splitlines()[-30:]
            log("DOCKER BUILD STDERR (tail):\n" + "\n".join(tail))
            report(
                task_id,
                phase="completed_failed",
                msg=f"Docker build failed (base={base_image}). See client.log tail.",
                status="failed",
            )
            return False

        report(task_id, phase="image_built", msg="Docker image built", progress=40, status="running")
        report(task_id, phase="container_started", msg="Starting container", progress=50, status="running")

        runres = subprocess.run(
            [docker_cmd, "run", "--rm", "-v", f"{task_dir}:/task", docker_image],
            cwd=task_dir,
            capture_output=True,
            text=True,
            env=_docker_env(),
        )
        report(task_id, phase="running", msg="Container running", progress=70, status="running")

        log(f"Docker STDOUT:\n{runres.stdout}")
        log(f"Docker STDERR:\n{runres.stderr}")

        if runres.returncode != 0:
            report(
                task_id,
                phase="completed_failed",
                msg=f"Container exitcode={runres.returncode}; stderr tail: {runres.stderr[-400:]}",
                status="failed",
            )
            return False

        return True
    except Exception as exc:
        log(f"Exception during docker run: {exc}")
        report(task_id, phase="completed_failed", msg=str(exc), status="failed")
        return False


def _zip_output_dir(output_dir: Path, result_zip: Path):
    if not output_dir.exists() or not any(output_dir.iterdir()):
        return False

    shutil.make_archive(
        str(result_zip).replace(".zip", ""),
        "zip",
        root_dir=str(output_dir.parent),
        base_dir="output",
    )
    return True


def process_task_zip(zip_path):
    task_file = Path(zip_path)
    if not task_file.name.endswith("_task.zip"):
        return False

    task_id = task_file.stem.replace("_task", "")
    work_dir = Path(WORK_BASE_DIR) / task_id
    result_zip = Path(RESULT_DIR) / f"{task_id}_result.zip"

    log(f"Processing task: {task_id}")
    report(task_id, phase="queued", msg="Task claimed by worker", progress=0, status="running")

    try:
        os.makedirs(work_dir, exist_ok=True)
        with zipfile.ZipFile(task_file, "r") as zip_ref:
            zip_ref.extractall(work_dir)
        log(f"Extracted task zip to {work_dir}")

        input_dir = work_dir / "input"
        config = load_task_config(str(work_dir))
        requires_input = config.get("requires_input", False)
        if requires_input and (not input_dir.exists() or not any(input_dir.iterdir())):
            msg = "Task requires input data, but input/ is empty"
            log(f"{msg}. Skipping.")
            report(task_id, phase="completed_failed", msg=msg, status="failed")
            report(task_id, phase="cleanup", msg="Cleaning up", status="failed")
            return False

        use_docker = config.get("use_docker", True)
        ok = run_docker_task(task_id, str(work_dir)) if use_docker else run_native_task(task_id, str(work_dir))

        if ok:
            report(task_id, phase="running", msg="Packaging result", progress=80, status="running")
            packed = _zip_output_dir(work_dir / "output", result_zip)
            if not packed:
                msg = "No output files found after execution."
                log(msg)
                report(task_id, phase="completed_failed", msg=msg, status="failed")
                return False

            log(f"Packaged result to {result_zip}")
            report(task_id, phase="running", msg="Uploading result", progress=90, status="running")
            uploaded = upload_result(task_id, result_zip)
            if uploaded:
                report(task_id, phase="completed_success", msg="Task finished and result uploaded", progress=100, status="success")
                return True

            report(task_id, phase="completed_failed", msg="Result upload failed", status="failed")
            return False

        return False
    except Exception as exc:
        log(f"Exception while processing task {task_id}: {exc}")
        report(task_id, phase="completed_failed", msg=str(exc), status="failed")
        return False
    finally:
        report(task_id, phase="cleanup", msg="Cleaning up")
        try:
            task_file.unlink(missing_ok=True)
            shutil.rmtree(work_dir, ignore_errors=True)
        finally:
            log(f"Cleaned up task {task_id}")


def download_task_zip(task_zip_name):
    url = f"{SERVER_URL}{API_BASE}/download_task/{task_zip_name}"
    local_path = os.path.join(TASK_ZIP_DIR, task_zip_name)

    log(f"Downloading task zip from {url} to {local_path}")
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        log(f"Error downloading {task_zip_name} from {url}: {exc}")
        raise

    with open(local_path, "wb") as f:
        f.write(resp.content)

    return local_path


def claim_task():
    raw = rds.brpoplpush(TASK_QUEUE_HIGH, PROCESSING_QUEUE_HIGH, timeout=1)
    if raw is not None:
        return TASK_QUEUE_HIGH, PROCESSING_QUEUE_HIGH, raw

    raw = rds.brpoplpush(TASK_QUEUE_NORMAL, PROCESSING_QUEUE_NORMAL, timeout=5)
    if raw is not None:
        return TASK_QUEUE_NORMAL, PROCESSING_QUEUE_NORMAL, raw

    return None


def ack_task(processing_queue, raw):
    rds.lrem(processing_queue, 1, raw)


def requeue_task(source_queue, processing_queue, raw):
    removed = rds.lrem(processing_queue, 1, raw)
    if removed:
        rds.rpush(source_queue, raw)


def recover_processing_queue(source_queue, processing_queue):
    while True:
        raw = rds.rpop(processing_queue)
        if raw is None:
            break
        rds.rpush(source_queue, raw)
        log(f"Recovered task from {processing_queue} back to {source_queue}")


def main():
    global CURRENT_TASK_ID
    log(f"Environment PATH: {os.environ.get('PATH')}")
    log(f"Worker ID: {WORKER_ID}")
    log(f"Processing queues: {PROCESSING_QUEUE_HIGH}, {PROCESSING_QUEUE_NORMAL}")
    recover_processing_queue(TASK_QUEUE_HIGH, PROCESSING_QUEUE_HIGH)
    recover_processing_queue(TASK_QUEUE_NORMAL, PROCESSING_QUEUE_NORMAL)
    log("Worker started, waiting for tasks from Redis (high + normal)...")

    heartbeat = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat.start()

    while True:
        source_queue = None
        processing_queue = None
        raw = None
        task_id = None

        try:
            claimed = claim_task()
            if not claimed:
                log("No tasks in queue, waiting...")
                continue

            source_queue, processing_queue, raw = claimed
            task_msg = json.loads(raw.decode("utf-8"))
            task_id = task_msg["task_id"]
            task_zip_name = task_msg["task_zip"]
            CURRENT_TASK_ID = task_id

            log(f"Got task from {source_queue}: task_id={task_id}, zip={task_zip_name}")
            local_zip_path = download_task_zip(task_zip_name)
            process_task_zip(local_zip_path)
            ack_task(processing_queue, raw)
            CURRENT_TASK_ID = None
        except Exception as exc:
            log(f"Worker loop error: {exc}")
            if task_id:
                report(task_id, phase="completed_failed", msg=str(exc), progress=100, status="failed")
            if source_queue and processing_queue and raw is not None:
                requeue_task(source_queue, processing_queue, raw)
            CURRENT_TASK_ID = None
            time.sleep(2)


if __name__ == "__main__":
    main()