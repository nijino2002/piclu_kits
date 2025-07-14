import os
import time
import logging
import shutil
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
import paramiko
from werkzeug.utils import secure_filename
from zipfile import ZipFile
from threading import Lock
from subprocess import run, CalledProcessError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

# 设置任务目录
home_dir = Path.home()
TASK_DIR = Path("/home/pi/task_manager/tasks") if os.path.exists("/home/pi") else home_dir / "task_manager" / "tasks"
os.makedirs(TASK_DIR, exist_ok=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # 当前脚本目录


app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # Max file size: 1GB
task_status_map = {}     # task_id -> status
status_lock = Lock()     # 多线程并发写保护

API_BASE = "/pi_task"

@app.route(API_BASE + '/')
def index():
    ip_groups = {}
    for f in sorted(TASK_DIR.glob("*_status.txt")):
        task_id = f.name.replace("_status.txt", "")
        result_file = TASK_DIR / f"{task_id}_result.zip"
        submit_time = None
        finish_time = None
        ip = "Unknown"
        use_docker = None
        task_type = "Unknown"

        with open(f, 'r') as sf:
            for line in sf:
                if line.startswith("Submitted at:"):
                    submit_time = line.strip().split(":", 1)[1].strip()
                elif line.startswith("Completed at:"):
                    finish_time = line.strip().split(":", 1)[1].strip()
                elif line.startswith("Client IP:"):
                    ip = line.strip().split(":", 1)[1].strip()
                elif line.startswith("Use Docker:"):
                    use_docker = line.strip().split(":", 1)[1].strip().lower() == "true"
                elif line.startswith("Task type:"):
                    task_type = line.strip().split(":", 1)[1].strip()

        task_info = {
            "id": task_id,
            "task_type": task_type,
            "has_result": result_file.exists(),
            "submit_time": submit_time,
            "finish_time": finish_time,
            "use_docker": use_docker
        }


        if ip not in ip_groups:
            ip_groups[ip] = []
        ip_groups[ip].append(task_info)

    return render_template('index.html', ip_groups=ip_groups)

@app.route(API_BASE + '/build_task', methods=['POST'])
def build_task():
    app.logger.info(f"Request headers: {dict(request.headers)}")
    app.logger.info(f"Request form keys: {list(request.form.keys())}")
    app.logger.info(f"Request files keys: {list(request.files.keys())}")
    try:
        task_mode = request.form.get("task_mode")
        import tempfile
        from subprocess import run

        app.logger.info(f"Received task_mode: {task_mode}")

        # 打印所有的表单数据
        for key, value in request.form.items():
            app.logger.info(f"Form data - {key}: {value}")

        # 打印上传的文件信息
        for file in request.files.values():
            app.logger.info(f"Received file - {file.filename}")

        with tempfile.TemporaryDirectory() as tmpdir:
            build_dir = Path(tmpdir)

            # 统一创建输出目录
            output_dir = build_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            if task_mode == "example":
                example_task = request.form.get("example_task")
                if not example_task:
                    return "缺少 example_task 参数", 400

                # 定义输出 zip 路径
                output_zip_path = output_dir / f"{example_task}_example_task.zip"

                if example_task == "aes_dec":
                    dep_zip = request.files.get("dep_zip")
                    if not dep_zip:
                        return "缺少依赖 ZIP", 400
                    dep_zip_path = build_dir / "dep.zip"
                    dep_zip.save(dep_zip_path)

                    cmd = [
                        f"{BASE_DIR}/myvenv/bin/python3",
                        f"{BASE_DIR}/build_task.py",
                        "-e", example_task,
                        "-d", str(dep_zip_path),
                        "-o", str(output_zip_path)
                    ]
                else:
                    cmd = [
                        f"{BASE_DIR}/myvenv/bin/python3",
                        f"{BASE_DIR}/build_task.py",
                        "-e", example_task,
                        "-o", str(output_zip_path)
                    ]

                result = run(cmd, cwd=build_dir, capture_output=True)
                if result.returncode != 0:
                    app.logger.error(f"Build_task.py failed:\nSTDOUT:\n{result.stdout.decode()}\nSTDERR:\n{result.stderr.decode()}")
                    return f"Build failed: {result.stderr.decode()}", 400

                zip_path = output_zip_path

            elif task_mode == "custom":
                task_name = request.form.get("custom_task_name")
                code_zip = request.files.get("code_zip")
                input_zip = request.files.get("input_zip")
                use_docker = request.form.get("use_docker") == "on"

                if not task_name or not code_zip:
                    return "Missing required fields", 400

                code_dir = build_dir / "code"
                input_dir = build_dir / "input"

                if code_dir.exists():
                    shutil.rmtree(code_dir)
                code_dir.mkdir(parents=True, exist_ok=True)

                # 保存并解压代码 zip
                code_zip_path = build_dir / "code.zip"
                code_zip.save(code_zip_path)
                with zipfile.ZipFile(code_zip_path, 'r') as zip_ref:
                    zip_ref.extractall(code_dir)

                # 处理输入 zip
                if input_zip:
                    if input_dir.exists():
                        shutil.rmtree(input_dir)
                    input_dir.mkdir(parents=True, exist_ok=True)
                    input_zip_path = build_dir / "input.zip"
                    input_zip.save(input_zip_path)
                    with zipfile.ZipFile(input_zip_path, 'r') as zip_ref:
                        zip_ref.extractall(input_dir)
                else:
                    input_dir = None

                output_zip_path = output_dir / f"{task_name}_user_task.zip"

                cmd = [
                    f"{BASE_DIR}/myvenv/bin/python3",
                    f"{BASE_DIR}/build_task.py",
                    "-i", str(code_dir),
                    "-o", str(output_zip_path),
                ]

                if input_dir:
                    cmd.extend(["-d", str(input_dir)])

                if not use_docker:
                    cmd.append("--no-docker")

                result = run(cmd, cwd=build_dir, capture_output=True)
                if result.returncode != 0:
                    app.logger.error(f"Build_task.py failed:\nSTDOUT:\n{result.stdout.decode()}\nSTDERR:\n{result.stderr.decode()}")
                    return f"Build failed: {result.stderr.decode()}", 400

                zip_path = output_zip_path

            else:
                return "Invalid task mode", 400

            if not zip_path.exists():
                return "Built zip not found", 500

            return send_from_directory(zip_path.parent, zip_path.name, as_attachment=True)

    except Exception:
        import traceback
        app.logger.error(traceback.format_exc())
        return "Internal Server Error", 500

@app.route(API_BASE + "/list_result_tasks")
def list_result_tasks():
    task_ids = []
    for filename in os.listdir(TASK_DIR):
        if filename.endswith("_result.zip"):
            task_id = filename[:-11]  # 去掉 _result.zip
            task_ids.append(task_id)
    return jsonify(task_ids)


@app.route(API_BASE + '/start_task', methods=['POST'])
def start_task():
    try:
        ip = request.form['ip']
        task_file = request.files['task_file']
        task_type = request.form['task_type']
        dependency_id = request.form.get('dependency_id', '').strip()

        timestamp = str(int(time.time()))
        filename = secure_filename(task_file.filename)
        task_id = timestamp
        saved_zip_name = f"{task_id}_task.zip"
        saved_zip_path = os.path.join(TASK_DIR, saved_zip_name)
        task_file.save(saved_zip_path)

        logger.info(f"Task file saved to {saved_zip_path}")

        if dependency_id:
            dep_result_path = os.path.join(TASK_DIR, f"{dependency_id}_result.zip")
            if os.path.exists(dep_result_path):
                import tempfile
                with tempfile.TemporaryDirectory() as tmpdir:
                    with ZipFile(dep_result_path, 'r') as dep_zip:
                        dep_zip.extractall(os.path.join(tmpdir, "input"))
                    task_unzip_path = os.path.join(tmpdir, "task")
                    os.makedirs(task_unzip_path, exist_ok=True)
                    with ZipFile(saved_zip_path, 'r') as task_zip:
                        task_zip.extractall(task_unzip_path)
                    shutil.copytree(os.path.join(tmpdir, "input"), os.path.join(task_unzip_path, "input"), dirs_exist_ok=True)
                    with ZipFile(saved_zip_path, 'w') as final_zip:
                        for root, dirs, files in os.walk(task_unzip_path):
                            for file in files:
                                abs_path = os.path.join(root, file)
                                rel_path = os.path.relpath(abs_path, task_unzip_path)
                                final_zip.write(abs_path, rel_path)
                logger.info(f"Dependency result from {dependency_id} injected.")
            else:
                logger.warning(f"Dependency result {dependency_id}_result.zip not found.")

        status_file = os.path.join(TASK_DIR, f"{task_id}_status.txt")
        with open(status_file, 'w') as f:
            f.write(f"Task {task_id} submitted.\n")
            f.write(f"Submitted at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Client IP: {ip}\n")
            f.write(f"Task type: {task_type}\n")
            if dependency_id:
                f.write(f"Depends on: {dependency_id}\n")

        result = distribute_task(ip, saved_zip_path, saved_zip_name)

        return jsonify({'status': 'success', 'message': result, 'task_id': task_id})
    except Exception as e:
        logger.exception("Failed to start task")
        return jsonify({'status': 'error', 'message': str(e)})

def distribute_task(ip, task_path, remote_name):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username='pi', password='111111')

        sftp = ssh.open_sftp()
        sftp.put(task_path, f'/home/pi/tasks/{remote_name}')
        sftp.close()
        ssh.close()

        logger.info(f"Task sent to {ip}")
        return f"Task sent to {ip}, waiting for execution"
    except Exception as e:
        logger.exception("SSH upload failed")
        return f"Failed to send task to {ip}: {str(e)}"

@app.route(API_BASE + '/task_status/<task_id>')
def task_status(task_id):
    status_file = os.path.join(TASK_DIR, f"{task_id}_status.txt")
    result_zip = os.path.join(TASK_DIR, f"{task_id}_result.zip")

    if not os.path.exists(status_file):
        return jsonify({'status': 'error', 'message': 'Task not found'})

    with open(status_file, 'r') as f:
        content = f.read()

    result_url = f"/download_result/{task_id}_result.zip" if os.path.exists(result_zip) else None

    return jsonify({'status': 'completed', 'log': content, 'result': result_url})

@app.route(API_BASE + "/task_status/<task_id>", methods=["GET"])
def get_task_status(task_id):
    with status_lock:
        status = task_status_map.get(task_id, "unknown")
    return jsonify({"task_id": task_id, "status": status})

@app.route(API_BASE + "/report_status/<task_id>", methods=["POST"])
def report_status(task_id):
    data = request.get_json()
    status = data.get("status")

    if status not in ("running", "success", "failed"):
        return jsonify({"error": "Invalid status"}), 400

    with status_lock:
        task_status_map[task_id] = status
    app.logger.info(f"[STATUS] Task {task_id} reported status: {status}")
    return jsonify({"message": "Status updated"}), 200

@app.route(API_BASE + '/upload_result/<filename>', methods=['POST'])
def upload_result(filename):
    file = request.files['file']
    save_path = os.path.join(TASK_DIR, filename)
    file.save(save_path)

    task_id = filename.replace("_result.zip", "")
    status_file = os.path.join(TASK_DIR, f"{task_id}_status.txt")

    # === 从 result.zip 里提取 use_docker 信息 ===
    try:
        import zipfile
        import json
        with zipfile.ZipFile(save_path, 'r') as zip_ref:
            zip_ref.extractall(f"/tmp/{task_id}_result")  # 临时解压

        # 尝试读取原任务包中的 config 文件
        task_zip_path = os.path.join(TASK_DIR, f"{task_id}_task.zip")
        if os.path.exists(task_zip_path):
            with zipfile.ZipFile(task_zip_path, 'r') as zip_ref:
                if "task_config.json" in zip_ref.namelist():
                    with zip_ref.open("task_config.json") as f:
                        config = json.load(f)
                        use_docker = config.get("use_docker", True)
                else:
                    use_docker = True
        else:
            use_docker = True
    except Exception as e:
        logger.warning(f"Failed to parse use_docker config: {e}")
        use_docker = True

    if os.path.exists(status_file):
        with open(status_file, 'a') as f:
            f.write(f"Completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Use Docker: {use_docker}\n")

    logger.info(f"Received result: {filename}")
    return jsonify({'status': 'success', 'message': 'Result uploaded successfully'})

@app.route(API_BASE + '/download_result/<filename>')
def download_result(filename):
    return send_from_directory(TASK_DIR, filename)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)