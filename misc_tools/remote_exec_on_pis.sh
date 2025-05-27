#!/bin/sh

# 初始化变量
NETWORK_PREFIX=""
ADDR_EXPR=""
REMOTE_CMD=""

SSH_OPTIONS="-o ConnectTimeout=3 -o BatchMode=yes"

# ANSI颜色
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# 参数解析
while [ $# -gt 0 ]; do
    case "$1" in
        -n)
            NETWORK_PREFIX=$2
            shift 2
            ;;
        -a)
            ADDR_EXPR=$2
            shift 2
            ;;
        -c)
            REMOTE_CMD=$2
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# 参数校验
if [ -z "$NETWORK_PREFIX" ] || [ -z "$ADDR_EXPR" ] || [ -z "$REMOTE_CMD" ]; then
    echo "Usage: $0 -n <network_prefix> -a [host_list] -c <command>" >&2
    echo "Example: $0 -n 192.168.12 -a [201-203,208] -c 'uptime'" >&2
    exit 1
fi

# 解析IP尾号列表
parse_host_range() {
    ADDR_EXPR_CLEAN=$(echo "$ADDR_EXPR" | sed 's/\[//; s/\]//')
    HOSTS=""
    OLD_IFS=$IFS
    IFS=','
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

# 主执行函数
execute_command() {
    for host in $HOSTS; do
        ip="$NETWORK_PREFIX.$host"
        echo "Executing on $ip..."
        if ssh $SSH_OPTIONS pi@"$ip" "$REMOTE_CMD"; then
            printf "${GREEN}[SUCCESS]${NC} %s\n" "$ip"
        else
            printf "${RED}[FAILED]${NC} %s\n" "$ip" >&2
        fi
    done
}

# 执行流程
parse_host_range
execute_command
