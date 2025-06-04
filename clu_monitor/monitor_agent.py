#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
import uuid

# Server 配置
SERVER_IP = "192.168.12.127"
SERVER_PORT = 5005
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

def get_ip(required_host_digits=3, required_host_prefix="2"):
    """
    获取符合特定规则的本地 IP 地址。

    参数:
    - required_host_digits (int or None): 指定主机号（IP 最后一段）的位数。
        - 可选值：1, 2, 3 或 None（不限制位数）
    - required_host_prefix (str or None): 指定主机号的前缀字符串（例如 '2'、'19' 等）。
        - None 表示不限制前缀。
        - 当指定为3位主机号时，仅允许以 '1' 或 '2' 开头。

    返回:
    - str: 匹配的 IPv4 地址，若无匹配，则返回第一个 192.168.12.* 地址，若仍无则返回 "0.0.0.0"
    """

    def is_valid_host(host_part):
        """
        检查主机号是否符合要求的位数和前缀。
        """
        if not host_part.isdigit():
            return False
        if required_host_digits and len(host_part) != required_host_digits:
            return False
        if required_host_prefix and not host_part.startswith(required_host_prefix):
            return False
        return True

    # 参数校验：主机位数合法性
    if required_host_digits not in [None, 1, 2, 3]:
        raise ValueError("required_host_digits must be None, 1, 2, or 3")

    # 参数校验：3位主机号必须以 '1' 或 '2' 开头
    if required_host_digits == 3 and required_host_prefix not in ["1", "2", None]:
        raise ValueError("3-digit host addresses must start with '1' or '2'")

    preferred = None  # 满足所有要求的 IP
    fallback = None   # 仅满足基础 192.168.12.* 格式的 IP

    # 遍历所有接口地址
    for iface_addrs in psutil.net_if_addrs().values():
        for addr in iface_addrs:
            if addr.family.name == 'AF_INET' and addr.address.startswith("192.168.12."):
                host_part = addr.address.split('.')[-1]

                if is_valid_host(host_part):
                    preferred = addr.address  # 找到满足条件的地址
                    break

                if fallback is None:
                    fallback = addr.address  # 缓存第一个基本匹配地址

    # 返回优先匹配地址，其次基本匹配，最后默认值
    return preferred or fallback or "0.0.0.0"

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
    while True:
        try:
            if not sio.connected:
                print(f"[INFO] Connecting to {SERVER_URL} ...")
                sio.connect(SERVER_URL)

            while sio.connected:
                metrics = collect_metrics()
                print("[DEBUG] Collected metrics:", metrics)
                sio.emit('metrics', json.dumps(metrics))
                print("[INFO] Metrics sent.")
                time.sleep(2)

        except Exception as e:
            print(f"[ERROR] Exception occurred: {e}")  # 打印异常原因
            time.sleep(5)

if __name__ == "__main__":
    main()
