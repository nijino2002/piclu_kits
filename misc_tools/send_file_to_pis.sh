#!/bin/sh

# 初始化变量
FILE_PATH=""
REMOTE_DIR=""
NETWORK_PREFIX=""
ADDR_EXPR=""
SSH_OPTIONS="-o ConnectTimeout=3 -o BatchMode=yes"

# ANSI颜色
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# 参数解析（POSIX兼容）
while [ $# -gt 0 ]; do
    case "$1" in
        -f)
            FILE_PATH=$2
            shift 2
            ;;
        -d)
            REMOTE_DIR=$2
            shift 2
            ;;
        -n)
            NETWORK_PREFIX=$2
            shift 2
            ;;
        -a)
            ADDR_EXPR=$2
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# 参数校验
if [ -z "$FILE_PATH" ] || [ -z "$REMOTE_DIR" ] || [ -z "$NETWORK_PREFIX" ] || [ -z "$ADDR_EXPR" ]; then
    echo "Usage: $0 -f <file> -d <remote_dir> -n <network_prefix> -a [host_list]" >&2
    echo "Example: $0 -f ./test.sh -d /home/pi/scripts -n 192.168.12 -a [201-203,205,208]" >&2
    exit 1
fi

# 文件存在性检查
if [ ! -f "$FILE_PATH" ]; then
    echo "Error: File '$FILE_PATH' not found" >&2
    exit 1
fi

# 解析IP尾号（支持 201-203,205,208 格式）
parse_host_range() {
    ADDR_EXPR_CLEAN=$(echo "$ADDR_EXPR" | sed 's/\[//; s/\]//')
    HOSTS=""
    OLD_IFS=$IFS
    IFS=','

    # 拆分逗号
    set -- $ADDR_EXPR_CLEAN
    for part in "$@"; do
        case "$part" in
            *-*)
                start=$(echo "$part" | cut -d'-' -f1)
                end=$(echo "$part" | cut -d'-' -f2)
                i=$start
                while [ "$i" -le "$end" ]; do
                    HOSTS="${HOSTS} $i"
                    i=$((i + 1))
                done
                ;;
            *)
                HOSTS="${HOSTS} $part"
                ;;
        esac
    done

    IFS=$OLD_IFS
}

# 创建远程目录
ensure_remote_dir() {
    ip="$1"
    ssh $SSH_OPTIONS pi@"$ip" "mkdir -p '$REMOTE_DIR'" >/dev/null 2>&1
    return $?
}

# 分发文件
distribute_file() {
    for host in $HOSTS; do
        ip="$NETWORK_PREFIX.$host"
        echo "Processing $ip..."

        if ensure_remote_dir "$ip"; then
            if scp $SSH_OPTIONS "$FILE_PATH" "pi@$ip:$REMOTE_DIR" >/dev/null 2>&1; then
                printf "${GREEN}[SUCCESS]${NC} %s\n" "$ip"
            else
                printf "${RED}[FAILED]${NC} %s (scp failed)\n" "$ip" >&2
            fi
        else
            printf "${RED}[FAILED]${NC} %s (ssh/mkdir failed)\n" "$ip" >&2
        fi
    done
}

# 执行
parse_host_range
distribute_file
