#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys

# 自动安装缺失的依赖
def ensure_dependencies(packages):
    import importlib
    for package in packages:
        try:
            importlib.import_module(package)
        except ImportError:
            print(f"[INFO] Installing missing package: {package}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

ensure_dependencies(["flask", "flask_socketio", "eventlet", "jinja2"])

# 主程序
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from threading import Lock
import json

SERVER_PORT = 5005      # Listen port
SERVER_IP = "0.0.0.0"   # Listen IP

app = Flask(__name__)
# 指定 async_mode='eventlet'，确保异步支持正常
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')
data_lock = Lock()
latest_metrics = {}

@app.route("/")
def index():
    return render_template("index.html")

@socketio.on('connect')
def handle_connect():
    print(f"[INFO] Client connected")
    # 连接时发送当前所有节点最新指标数据
    with data_lock:
        emit('init', latest_metrics)

@socketio.on('disconnect')
def handle_disconnect():
    print(f"[INFO] Client disconnected")

@socketio.on('metrics')
def handle_metrics(msg):
    global latest_metrics
    try:
        data = json.loads(msg)
        node_id = data.get("node")
        if node_id:
            with data_lock:
                latest_metrics[node_id] = data
            # 广播更新给所有连接的客户端
            socketio.emit('update', data)
            print(f"[INFO] Updated metrics from node: {node_id}")
        else:
            print("[WARN] Received metrics without node id")
    except Exception as e:
        print("[ERROR] Invalid data received:", e)

if __name__ == "__main__":
    print("[INFO] Starting monitoring server on http://0.0.0.0:5000")
    # 启用 debug 模式，方便调试
    socketio.run(app, host=SERVER_IP, port=SERVER_PORT, debug=True)
