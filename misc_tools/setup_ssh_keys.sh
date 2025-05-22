
#!/bin/bash

# 可配置参数
START_IP=201
END_IP=210
NETWORK_PREFIX="192.168.12"
SSH_USER="pi"
SSH_PASS="111111"
KEY_FILE="$HOME/.ssh/id_rsa.pub"

# 检查本地密钥是否存在
check_local_key() {
    [ ! -f "$KEY_FILE" ] && {
        echo "Generating new SSH key..."
        ssh-keygen -t rsa -N "" -f "${KEY_FILE%.pub}"
    }
}

# 单节点密钥分发
distribute_key() {
    local ip="$1"
    sshpass -p "$SSH_PASS" ssh-copy-id \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout=5 \
        "${SSH_USER}@${ip}" 2>/dev/null
}

# 主分发流程
main() {
    check_local_key
    local i=$START_IP
    
    while [ $i -le $END_IP ]; do
        local ip="${NETWORK_PREFIX}.$i"
        echo -n "Processing $ip..."
        
        if distribute_key "$ip"; then
            echo " [OK]"
        else
            echo " [FAILED]" >&2
        fi
        i=$((i+1))
    done
}

main
