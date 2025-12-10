# client.py - Redis 优先级队列 + 原有高级执行逻辑（融合版）

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
import redis  # Redis 客户端

# ===================== 基本配置 =====================
TASK_ZIP_DIR = "/home/pi/tasks"
WORK_BASE_DIR = "/home/pi/task_manager/work"
RESULT_DIR = "/home/pi/task_manager/results"
LOG_FILE_PATH = "/home/pi/task_manager/client.log"

SERVER_URL = "http://192.168.12.201:5000"  # 管理端地址（master）
API_BASE = "/pi_task"                      # 后端统一前缀

# Redis 配置（调度用）
REDIS_HOST = "192.168.12.201"   # master 的 IP（跑 Redis 的那台）
REDIS_PORT = 6379
TASK_QUEUE_HIGH = "pi_task_high"      # 高优先级队列名，要和 master 保持一致
TASK_QUEUE_NORMAL = "pi_task_normal"  # 普通优先级队列名

# 镜像源候选（会按顺序尝试）
BASE_IMAGE_CANDIDATES = [
    "python:3.11-slim-bookworm",                          # 官方（优先）
    "dockerproxy.net/library/python:3.11-slim-bookworm",  # 代理备选
]

# 可选 PyPI 源（传空字符串则用官方）
DEFAULT_PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
# 若你希望默认走官方，把上面改成 "" 即可

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

# Redis 连接（程序启动就连一次）
rds = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)


# ===================== 上报工具函数 =====================
def report(task_id, phase=None, msg=None, progress=None, status=None):
    """向后端上报任务阶段/状态。status 可省略，后端会按 phase 推导。"""
    payload = {}
    if phase is not None:
        payload["phase"] = phase
    if msg is not None:
        payload["msg"] = msg
    if progress is not None:
        payload["progress"] = progress
    if status is not None:
        payload["status"] = status
    try:
        r = requests.post(
            f"{SERVER_URL}{API_BASE}/report_status/{task_id}",
            json=payload,
            timeout=5,
        )
        log(f"Report status ({phase}): {r.status_code}")
    except Exception as e:
        log(f"Report status failed: {e}")


# ===================== 任务配置 =====================
def load_task_config(task_dir):
    config_path = os.path.join(task_dir, "task_config.json")
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception as e:
        log(f"Failed to load config: {e}. Defaulting to use_docker=True")
        return {"use_docker": True}


# ===================== 结果上传 =====================
def upload_result(task_id, result_zip_path):
    try:
        with open(result_zip_path, "rb") as f:
            files = {"file": f}
            resp = requests.post(
                f"{SERVER_URL}{API_BASE}/upload_result/{task_id}_result.zip",
                files=files,
                timeout=60,
            )
        log(f"Upload response: {resp.status_code} - {resp.text}")
        return 200 <= resp.status_code < 300
    except Exception as e:
        log(f"Failed to upload result: {e}")
        return False


# ===================== 本地执行（非容器） =====================
def run_native_task(task_id, task_dir):
    report(task_id, phase="container_started", msg="Starting native run", progress=45, status="running")
    try:
        req_file = os.path.join(task_dir, "requirements.txt")
        if os.path.exists(req_file):
            report(task_id, phase="running", msg="Installing requirements (native)", progress=50)
            subprocess.run(["pip3", "install", "-r", req_file], check=False)

        main_file = os.path.join(task_dir, "main.py")
        report(task_id, phase="running", msg="Executing main.py (native)", progress=60)
        result = subprocess.run(
            ["python3", main_file],
            cwd=task_dir,
            capture_output=True,
            text=True
        )
        log(f"NATIVE STDOUT:\n{result.stdout}")
        log(f"NATIVE STDERR:\n{result.stderr}")

        if result.returncode != 0:
            report(task_id, phase="completed_failed", msg=f"Native run exitcode={result.returncode}", status="failed")
            return False
        return True
    except subprocess.CalledProcessError as e:
        log(f"Error during native execution: {e}")
        report(task_id, phase="completed_failed", msg=str(e), status="failed")
        return False
    except Exception as e:
        log(f"Exception during native execution: {e}")
        report(task_id, phase="completed_failed", msg=str(e), status="failed")
        return False


# ===================== 容器执行 =====================
def _resolve_docker_path():
    for p in ("/usr/bin/docker", "/usr/local/bin/docker"):
        if os.path.exists(p):
            return p
    return sh.which("docker")

def _docker_env():
    """构建 docker 子进程的环境：开启 BuildKit，并透传代理环境变量。"""
    env = os.environ.copy()
    env["DOCKER_BUILDKIT"] = "1"
    # 如果宿主机设置了代理，透传给 build 过程（让拉取依赖时也能走代理）
    for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy"):
        if k in os.environ:
            env[k] = os.environ[k]
    return env

def _docker_pull_with_retry(docker_cmd, image, retries=3, sleep_sec=3):
    """带重试的 docker pull；返回 True/False。"""
    for i in range(1, retries+1):
        pull = subprocess.run(
            [docker_cmd, "pull", image],
            capture_output=True, text=True, env=_docker_env()
        )
        if pull.returncode == 0:
            return True
        tail = pull.stderr.strip().splitlines()[-10:]
        log(f"DOCKER PULL BASE STDERR (tail):\n" + "\n".join(tail))
        time.sleep(sleep_sec * i)
    return False

def _select_base_image(docker_cmd):
    """按候选列表依次尝试预拉，返回可用的基础镜像字符串；否则返回 None。"""
    for base in BASE_IMAGE_CANDIDATES:
        ok = _docker_pull_with_retry(docker_cmd, base)
        if ok:
            return base
    return None

def run_docker_task(task_id, task_dir):
    docker_cmd = _resolve_docker_path()
    if not docker_cmd:
        msg = "Docker command not found in PATH"
        log(msg)
        report(task_id, phase="completed_failed", msg=msg, status="failed")
        return False

    # 选基础镜像：先官方，失败再代理；都失败就直接判定失败
    base_image = _select_base_image(docker_cmd)
    if not base_image:
        msg = "Failed to pull any base image candidates"
        log(msg)
        report(task_id, phase="completed_failed", msg=msg, status="failed")
        return False

    docker_image = f"task_image_{task_id}"

    try:
        report(task_id, phase="image_build", msg=f"Building Docker image from {base_image}", progress=20, status="running")

        # 通过 --build-arg 把 BASE_IMAGE 和 PIP_INDEX_URL 传进 Dockerfile
        build_cmd = [
            docker_cmd, "build", "--pull",
            "--build-arg", f"BASE_IMAGE={base_image}",
            "--build-arg", f"PIP_INDEX_URL={DEFAULT_PYPI_MIRROR}",
            "-t", docker_image, "."
        ]

        build = subprocess.run(
            build_cmd,
            cwd=task_dir,
            capture_output=True,
            text=True,
            env=_docker_env()
        )
        if build.returncode != 0:
            tail = (build.stderr or "").strip().splitlines()[-30:]
            log("DOCKER BUILD STDERR (tail):\n" + "\n".join(tail))
            report(task_id, phase="completed_failed",
                   msg=f"Docker build failed (base={base_image}). See client.log tail.",
                   status="failed")
            return False

        report(task_id, phase="image_built", msg="Docker image built", progress=40)
        report(task_id, phase="container_started", msg="Starting container", progress=50)

        runres = subprocess.run(
            [docker_cmd, "run", "--rm", "-v", f"{task_dir}:/task", docker_image],
            cwd=task_dir,
            capture_output=True,
            text=True,
            env=_docker_env()
        )
        report(task_id, phase="running", msg="Container running", progress=70)

        log(f"Docker STDOUT:\n{runres.stdout}")
        log(f"Docker STDERR:\n{runres.stderr}")

        if runres.returncode != 0:
            report(task_id, phase="completed_failed",
                   msg=f"Container exitcode={runres.returncode}; stderr tail: {runres.stderr[-400:]}",
                   status="failed")
            return False

        return True

    except subprocess.CalledProcessError as e:
        log(f"Docker error: {e}")
        report(task_id, phase="completed_failed", msg=str(e), status="failed")
        return False
    except Exception as e:
        log(f"Exception during docker run: {e}")
        report(task_id, phase="completed_failed", msg=str(e), status="failed")
        return False


# ===================== 打包 output 目录 =====================
def _zip_output_dir(output_dir: Path, result_zip: Path):
    if not output_dir.exists():
        return False
    if not any(output_dir.iterdir()):
        return False
    # 关键：root_dir 指向工作目录，base_dir 指向 'output'，从而 zip 里是 output/xxx
    work_dir = output_dir.parent
    shutil.make_archive(str(result_zip).replace(".zip", ""), "zip",
                        root_dir=str(work_dir), base_dir="output")
    return True


# ===================== 处理任务 ZIP（保持旧版逻辑） =====================
def process_task_zip(zip_path):
    task_file = Path(zip_path)
    if not task_file.name.endswith("_task.zip"):
        return

    task_id = task_file.stem.replace("_task", "")
    work_dir = Path(WORK_BASE_DIR) / task_id
    result_zip = Path(RESULT_DIR) / f"{task_id}_result.zip"

    log(f"Processing task: {task_id}")
    report(task_id, phase="queued", msg="Task queued on client", progress=0, status="running")

    try:
        os.makedirs(work_dir, exist_ok=True)
        with zipfile.ZipFile(task_file, "r") as zip_ref:
            zip_ref.extractall(work_dir)
        log(f"Extracted task zip to {work_dir}")

        input_dir = work_dir / "input"
        if input_dir.exists() and not any(input_dir.iterdir()):
            msg = "Task requires input data, but input/ is empty"
            log(f"{msg}. Skipping.")
            report(task_id, phase="completed_failed", msg=msg, status="failed")
            report(task_id, phase="cleanup", msg="Cleaning up")
            return

        config = load_task_config(str(work_dir))
        use_docker = config.get("use_docker", True)

        ok = run_docker_task(task_id, str(work_dir)) if use_docker else run_native_task(task_id, str(work_dir))

        if ok:
            report(task_id, phase="running", msg="Packaging result", progress=80)
            output_dir = work_dir / "output"
            packed = _zip_output_dir(output_dir, result_zip)
            if not packed:
                msg = "No output files found after execution."
                log(msg)
                report(task_id, phase="completed_failed", msg=msg, status="failed")
            else:
                log(f"Packaged result to {result_zip}")
                report(task_id, phase="running", msg="Uploading result", progress=90)
                uploaded = upload_result(task_id, result_zip)
                if uploaded:
                    report(task_id, phase="completed_success", msg="Task finished and result uploaded", progress=100, status="success")
                else:
                    report(task_id, phase="completed_failed", msg="Result upload failed", status="failed")

        report(task_id, phase="cleanup", msg="Cleaning up")
    except Exception as e:
        log(f"Exception while processing task {task_id}: {e}")
        report(task_id, phase="completed_failed", msg=str(e), status="failed")
        report(task_id, phase="cleanup", msg="Cleaning up after failure")
    finally:
        try:
            task_file.unlink(missing_ok=True)
            shutil.rmtree(work_dir, ignore_errors=True)
        finally:
            log(f"Cleaned up task {task_id}")


# ===================== 从 master 下载任务 ZIP =====================
def download_task_zip(task_zip_name: str) -> str:
    """
    从 master 下载任务 zip 保存到本地 TASK_ZIP_DIR，返回本地路径。
    """
    url = f"{SERVER_URL}{API_BASE}/download_task/{task_zip_name}"
    local_path = os.path.join(TASK_ZIP_DIR, task_zip_name)

    log(f"Downloading task zip from {url} to {local_path}")
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()  # 如果请求失败，会抛出异常
    except requests.exceptions.RequestException as e:
        log(f"Error downloading {task_zip_name} from {url}: {e}")
        raise  # 抛给上层，让 main() 记录错误

    with open(local_path, "wb") as f:
        f.write(resp.content)

    return local_path


# ===================== 主循环 =====================
def main():
    log(f"Environment PATH: {os.environ.get('PATH')}")
    log("Worker started, waiting for tasks from Redis (high + normal)...")

    while True:
        try:
            # 阻塞等待队列任务，优先从高优队列取
            res = rds.blpop([TASK_QUEUE_HIGH, TASK_QUEUE_NORMAL], timeout=5)
            if not res:
                # 5 秒内没有任务，打印一条日志方便确认 worker 活着
                log("No tasks in queue, waiting...")
                continue

            queue_name, raw = res
            queue_name = queue_name.decode("utf-8")
            task_msg = json.loads(raw.decode("utf-8"))
            task_id = task_msg["task_id"]
            task_zip_name = task_msg["task_zip"]

            log(f"Got task from {queue_name}: task_id={task_id}, zip={task_zip_name}")

            # 1. 从 master 下载任务 zip 到本地
            local_zip_path = download_task_zip(task_zip_name)

            # 2. 复用原来的处理逻辑
            process_task_zip(local_zip_path)

        except Exception as e:
            log(f"Worker loop error: {e}")
            time.sleep(2)


if __name__ == "__main__":
    main()
