# client.py
import os
import time
import zipfile
import subprocess
import requests
import shutil
from pathlib import Path
import logging

TASK_ZIP_DIR = "/home/pi/tasks"
WORK_BASE_DIR = "/home/pi/task_manager/work"
RESULT_DIR = "/home/pi/task_manager/results"
LOG_FILE_PATH = "/home/pi/task_manager/client.log"
SERVER_URL = "http://192.168.12.127:5000"  # 管理端地址

os.makedirs(TASK_ZIP_DIR, exist_ok=True)
os.makedirs(WORK_BASE_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

# === 日志 ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.FileHandler(LOG_FILE_PATH), logging.StreamHandler()]
)
logger = logging.getLogger("client")

def log(msg): logger.info(msg)

def upload_result(task_id, result_zip_path):
    try:
        with open(result_zip_path, "rb") as f:
            files = {"file": f}
            response = requests.post(f"{SERVER_URL}/upload_result/{task_id}_result.zip", files=files)
            log(f"Upload response: {response.status_code} - {response.text}")
    except Exception as e:
        log(f"Failed to upload result: {e}")

def run_docker_task(task_id, task_dir):
    docker_image = f"task_image_{task_id}"
    try:
        log(f"Building Docker image for task {task_id}")
        subprocess.run(["docker", "build", "-t", docker_image, "."], cwd=task_dir, check=True)

        log(f"Running Docker container for task {task_id}")
        result = subprocess.run(
            ["docker", "run", "--rm", "-v", f"{task_dir}:/task", docker_image],
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

        # 检查 input/ 是否存在且为空
        input_dir = work_dir / "input"
        if input_dir.exists() and not any(input_dir.iterdir()):
            log(f"Task {task_id} requires input data, but input/ is empty. Skipping task.")
            return

        run_docker_task(task_id, str(work_dir))

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


def main():
    log("Client started.")
    while True:
        try:
            for file in os.listdir(TASK_ZIP_DIR):
                full_path = os.path.join(TASK_ZIP_DIR, file)
                process_task_zip(full_path)
        except Exception as e:
            log(f"Error: {e}")
        time.sleep(5)

if __name__ == "__main__":
    main()
    