
#!/bin/sh

# 参数校验
if [ $# -lt 2 ]; then
    echo "Usage: $0 <file_to_send> <remote_directory>" >&2
    echo "Example: $0 monitor.sh /home/pi/scripts/" >&2
    exit 1
fi

# 配置参数
START_IP=201
END_IP=210
NETWORK_PREFIX="192.168.12"
REMOTE_DIR="$2"  # 从第二个参数获取目标目录

# 确保远程目录存在
ensure_remote_dir() {
    local ip="$1"
    ssh pi@"$ip" "mkdir -p '$REMOTE_DIR' || { echo 'Directory creation failed' >&2; exit 1; }"
}

# 主分发函数
distribute_file() {
    local file_path="$1"
    local i=$START_IP
    
    while [ $i -le $END_IP ]; do
        local ip="${NETWORK_PREFIX}.$i"
        echo "Processing $ip..."
        
        if ensure_remote_dir "$ip"; then
            if scp -o BatchMode=yes "$file_path" "pi@$ip:$REMOTE_DIR"; then
                echo "[SUCCESS] $ip"
            else
                echo "[FAILED] $ip" >&2
            fi
        fi
        i=$((i+1))
    done
}

# 文件存在性检查
[ ! -f "$1" ] && echo "Error: File '$1' not found" >&2 && exit 1

distribute_file "$1"
