import os
import time
import logging
import shutil
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
import paramiko
from werkzeug.utils import secure_filename
from zipfile import ZipFile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

# 设置任务目录
home_dir = Path.home()
TASK_DIR = Path("/home/pi/task_manager/tasks") if os.path.exists("/home/pi") else home_dir / "task_manager" / "tasks"
os.makedirs(TASK_DIR, exist_ok=True)

app = Flask(__name__)

@app.route('/')
def index():
    ip_groups = {}
    for f in sorted(TASK_DIR.glob("*_status.txt")):
        task_id = f.name.replace("_status.txt", "")
        result_file = TASK_DIR / f"{task_id}_result.zip"
        submit_time = None
        finish_time = None
        ip = "Unknown"
        use_docker = None
        
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

        task_info = {
            "id": task_id,
            "has_result": result_file.exists(),
            "submit_time": submit_time,
            "finish_time": finish_time,
            "use_docker": use_docker
        }


        if ip not in ip_groups:
            ip_groups[ip] = []
        ip_groups[ip].append(task_info)

    return render_template('index.html', ip_groups=ip_groups)

@app.route("/list_result_tasks")
def list_result_tasks():
    task_ids = []
    for filename in os.listdir(TASK_DIR):
        if filename.endswith("_result.zip"):
            task_id = filename[:-11]  # 去掉 _result.zip
            task_ids.append(task_id)
    return jsonify(task_ids)


@app.route('/start_task', methods=['POST'])
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

@app.route('/task_status/<task_id>')
def task_status(task_id):
    status_file = os.path.join(TASK_DIR, f"{task_id}_status.txt")
    result_zip = os.path.join(TASK_DIR, f"{task_id}_result.zip")

    if not os.path.exists(status_file):
        return jsonify({'status': 'error', 'message': 'Task not found'})

    with open(status_file, 'r') as f:
        content = f.read()

    result_url = f"/download_result/{task_id}_result.zip" if os.path.exists(result_zip) else None

    return jsonify({'status': 'completed', 'log': content, 'result': result_url})

@app.route('/upload_result/<filename>', methods=['POST'])
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

@app.route('/download_result/<filename>')
def download_result(filename):
    return send_from_directory(TASK_DIR, filename)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)