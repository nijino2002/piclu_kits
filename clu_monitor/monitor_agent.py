#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
import uuid

# Server 配置
SERVER_IP = "192.168.12.127"
SERVER_PORT = 5000
SERVER_URL = f"http://{SERVER_IP}:{SERVER_PORT}"

# 自动安装依赖
def ensure_dependencies(packages):
    # pip 包名与 import 名可能不同，建立映射
    package_mapping = {
        "socketio": "python-socketio"
    }
    for pkg in packages:
        import_name = pkg
        pip_name = package_mapping.get(pkg, pkg)
        try:
            __import__(import_name)
        except ImportError:
            print(f"[INFO] Installing missing package: {pip_name}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])

ensure_dependencies(["psutil", "socketio", "requests"])

# 导入依赖
import psutil
import socket
import time
import json
import socketio  # 注意：这是 python-socketio，不是 websocket-client

# 获取节点名
hostname = socket.gethostname()

# 初始化 socketio 客户端
sio = socketio.Client(reconnection=True)

@sio.event
def connect():
    print(f"[INFO] Connected to server {SERVER_URL}")

@sio.event
def disconnect():
    print("[INFO] Disconnected from server")

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "0.0.0.0"

def get_mac():
    mac_num = hex(uuid.getnode()).replace('0x', '').upper()
    mac = ":".join(mac_num[i:i+2] for i in range(0, 12, 2))
    return mac

def collect_metrics():
    return {
        "node": hostname + "-" + get_ip(),
        "timestamp": int(time.time()),
        "cpu": psutil.cpu_percent(),
        "memory": psutil.virtual_memory().percent,
        "net_in": psutil.net_io_counters().bytes_recv,
        "net_out": psutil.net_io_counters().bytes_sent,
        "ip": get_ip(),
        "mac": get_mac(),
        "bandwidth_mbps": get_max_bandwidth()
    }

def get_max_bandwidth(interface="eth0"):
    try:
        result = subprocess.check_output(["cat", f"/sys/class/net/{interface}/speed"], stderr=subprocess.DEVNULL)
        return int(result.decode().strip())
    except Exception:
        return 100  # 默认设为 100 Mbps，如果读取失败

def main():
    try:
        print(f"[INFO] Connecting to {SERVER_URL} ...")
        sio.connect(SERVER_URL)
        while True:
            metrics = collect_metrics()
            sio.emit('metrics', json.dumps(metrics))
            time.sleep(2)
    except Exception as e:
        print(f"[ERROR] {e}")
        time.sleep(5)
        main()  # 自动重连

if __name__ == "__main__":
    main()
