import os
import time
import zipfile
import subprocess
import requests
import shutil
from pathlib import Path
import logging
import json
import shutil as sh
import redis

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

rds = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

os.makedirs(TASK_ZIP_DIR, exist_ok=True)
os.makedirs(WORK_BASE_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.FileHandler(LOG_FILE_PATH), logging.StreamHandler()]
)
logger = logging.getLogger("client")

def log(msg):
    logger.info(msg)

def load_task_config(task_dir):
    config_path = os.path.join(task_dir, "task_config.json")
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception as e:
        log(f"Failed to load config: {e}. Defaulting to use_docker=True")
        return {"use_docker": True}

def upload_result(task_id, result_zip_path):
    try:
        with open(result_zip_path, "rb") as f:
            files = {"file": f}
            response = requests.post(f"{SERVER_URL}{API_BASE}/upload_result/{task_id}_result.zip", files=files)
            log(f"Upload response: {response.status_code} - {response.text}")
    except Exception as e:
        log(f"Failed to upload result: {e}")

def run_native_task(task_id, task_dir):
    log(f"Running task {task_id} natively")
    try:
        req_file = os.path.join(task_dir, "requirements.txt")
        if os.path.exists(req_file):
            log(f"Installing requirements for task {task_id}")
            subprocess.run(["pip3", "install", "-r", req_file], check=False)

        main_file = os.path.join(task_dir, "main.py")
        result = subprocess.run(
            ["python3", main_file],
            cwd=task_dir,
            capture_output=True,
            text=True
        )
        log(f"NATIVE STDOUT:\n{result.stdout}")
        log(f"NATIVE STDERR:\n{result.stderr}")
    except subprocess.CalledProcessError as e:
        log(f"Error during Docker build/run: {e}")
        log(f"STDOUT: {e.stdout}")
        log(f"STDERR: {e.stderr}")


def run_docker_task(task_id, task_dir):
    docker_cmd = "/usr/bin/docker"  # ← 直接指定绝对路径
    if not os.path.exists(docker_cmd):
        log(f"Docker command not found at {docker_cmd}")
        return

    docker_image = f"task_image_{task_id}"
    try:
        log(f"Building Docker image for task {task_id} using {docker_cmd}")
        subprocess.run([docker_cmd, "build", "-t", docker_image, "."], cwd=task_dir, check=True)

        log(f"Running Docker container for task {task_id}")
        result = subprocess.run(
            [docker_cmd, "run", "--rm", "-v", f"{task_dir}:/task", docker_image],
            cwd=task_dir,
            capture_output=True,
            text=True
        )
        log(f"Docker STDOUT:\n{result.stdout}")
        log(f"Docker STDERR:\n{result.stderr}")
    except subprocess.CalledProcessError as e:
        log(f"Error during Docker build/run: {e}")


def process_task_zip(zip_path):
    task_file = Path(zip_path)
    if not task_file.name.endswith("_task.zip"):
        return

    task_id = task_file.stem.replace("_task", "")
    work_dir = Path(WORK_BASE_DIR) / task_id
    result_zip = Path(RESULT_DIR) / f"{task_id}_result.zip"

    log(f"Processing task: {task_id}")

    try:
        os.makedirs(work_dir, exist_ok=True)
        with zipfile.ZipFile(task_file, "r") as zip_ref:
            zip_ref.extractall(work_dir)
        log(f"Extracted task zip to {work_dir}")

        input_dir = work_dir / "input"
        if input_dir.exists() and not any(input_dir.iterdir()):
            log(f"Task {task_id} requires input data, but input/ is empty. Skipping task.")
            return

        config = load_task_config(str(work_dir))
        if config.get("use_docker", True):
            run_docker_task(task_id, str(work_dir))
        else:
            run_native_task(task_id, str(work_dir))

        output_dir = work_dir / "output"
        if not output_dir.exists() or not any(output_dir.iterdir()):
            log(f"No output directory or files found for task {task_id}, skipping packaging.")
            return

        shutil.make_archive(str(result_zip).replace(".zip", ""), "zip", root_dir=output_dir)
        log(f"Packaged result to {result_zip}")
        upload_result(task_id, result_zip)

    except Exception as e:
        log(f"Exception while processing task {task_id}: {e}")
    finally:
        task_file.unlink(missing_ok=True)
        shutil.rmtree(work_dir, ignore_errors=True)
        log(f"Cleaned up task {task_id}")

def download_task_zip(task_zip_name):
    url = f"{SERVER_URL}{API_BASE}/download_task/{task_zip_name}"
    local_path = os.path.join(TASK_ZIP_DIR, task_zip_name)

    log(f"Downloading task zip from {url} to {local_path}")
    try:
        resp = requests.get(url)
        resp.raise_for_status()  # 如果请求失败，会抛出异常
    except requests.exceptions.RequestException as e:
        log(f"Error downloading {task_zip_name} from {url}: {e}")
        raise  # 重新抛出异常，便于上层处理

    with open(local_path, "wb") as f:
        f.write(resp.content)

    return local_path

def main():
    log(f"Environment PATH: {os.environ.get('PATH')}")
    log("Worker started, waiting for tasks from Redis...")

    while True:
        try:
            # 阻塞等待队列任务，timeout=5 秒只是为了有机会打印日志/重连
            res = rds.blpop([TASK_QUEUE_HIGH, TASK_QUEUE_NORMAL], timeout=5)
            if not res:
                log("No tasks in queue, waiting...")
                continue

            queue_name, raw = res
            queue_name = queue_name.decode("utf-8")
            task_msg = json.loads(raw.decode("utf-8"))
            task_id = task_msg["task_id"]
            task_zip_name = task_msg["task_zip"]

            log(f"Got task from {queue_name} task_id={task_id}, zip={task_zip_name}")

            # 1. 先从 master 下载任务 zip 到本地 TASK_ZIP_DIR
            local_zip_path = download_task_zip(task_zip_name)

            # 2. 处理这个 zip
            process_task_zip(local_zip_path)

        except Exception as e:
            log(f"Worker loop error: {e}")
            time.sleep(2)


if __name__ == "__main__":
    main()
