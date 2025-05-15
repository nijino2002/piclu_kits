#!/bin/sh

MAP_FILE="$1"
USERNAME="pi"
PASSWORD="111111"
ROUTER_IP="192.168.12.1"
DNS_SERVERS="8.8.8.8 8.8.4.4"

log() {
    echo "🔧 $1"
}

debug() {
    echo "🐞 [DEBUG] $1"
}

install_tool_if_needed() {
    TOOL_NAME=$1
    if ! command -v "$TOOL_NAME" > /dev/null 2>&1; then
        log "$TOOL_NAME 未安装，正在安装..."
        sudo apt-get update
        sudo apt-get install -y "$TOOL_NAME"
    else
        debug "$TOOL_NAME 已安装"
    fi
}

check_and_install_local_tools() {
    install_tool_if_needed "arp-scan"
    install_tool_if_needed "sshpass"
}

validate_map_file() {
    if [ ! -f "$MAP_FILE" ]; then
        echo "❌ 映射文件 $MAP_FILE 不存在"
        exit 1
    fi
    while IFS= read -r line || [ -n "$line" ]; do
        echo "$line" | grep -Eq '^#|^$' && continue
        trimmed=$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        echo "$trimmed" | grep -Eq "^([0-9a-f]{2}:){5}[0-9a-f]{2}[[:space:],]+([0-9]{1,3}\.){3}[0-9]{1,3}$" || {
            echo "❌ 错误行: $trimmed"
            echo "格式应为：mac [空格/tab/逗号] ip"
            exit 1
        }
    done < "$MAP_FILE"
    log "映射文件格式正确"
}

get_network_interface() {
    ip route | awk '/default/ {print $5}' | head -n1
}

remote_install_network_tools() {
    IP=$1
    sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$USERNAME@$IP" <<EOF
        echo "🔧 检查网络服务..."
        if ! command -v dhcpcd >/dev/null 2>&1; then
            echo "未找到 dhcpcd，尝试安装..."
            sudo apt-get update && sudo apt-get install -y dhcpcd5
        fi
        if ! command -v nmcli >/dev/null 2>&1; then
            echo "未找到 NetworkManager，尝试安装..."
            sudo apt-get update && sudo apt-get install -y network-manager
        fi
EOF
}

configure_static_ip_remote() {
    MAC=$1
    TARGET_IP=$2
    CUR_IP=$3

    log "配置 $MAC（当前 IP: $CUR_IP） ➜ 静态 IP: $TARGET_IP"

    sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$USERNAME@$CUR_IP" <<EOF
        echo "🚧 检查是否有 dhcpcd..."
        if command -v dhcpcd >/dev/null 2>&1; then
            sudo sed -i '/^interface eth0/,+4d' /etc/dhcpcd.conf
            sudo tee -a /etc/dhcpcd.conf > /dev/null <<EOL
interface eth0
static ip_address=$TARGET_IP/24
static routers=$ROUTER_IP
static domain_name_servers=$DNS_SERVERS
EOL
            echo "🔁 重启 dhcpcd..."
            sudo systemctl restart dhcpcd || echo "⚠️ 重启 dhcpcd 失败"
        elif command -v nmcli >/dev/null 2>&1; then
            CON_NAME=\$(nmcli -t -f NAME,DEVICE con show --active | grep eth0 | cut -d: -f1)
            sudo nmcli con mod "\$CON_NAME" ipv4.addresses "$TARGET_IP/24"
            sudo nmcli con mod "\$CON_NAME" ipv4.gateway "$ROUTER_IP"
            sudo nmcli con mod "\$CON_NAME" ipv4.dns "$DNS_SERVERS"
            sudo nmcli con mod "\$CON_NAME" ipv4.method manual
            sudo nmcli con down "\$CON_NAME" && sudo nmcli con up "\$CON_NAME"
        else
            echo "❌ 无可用网络配置工具"
            exit 1
        fi
EOF
    if [ $? -eq 0 ]; then
        echo "✅ $MAC 配置完成: $TARGET_IP"
    else
        echo "❌ $MAC 配置失败: $CUR_IP ➜ $TARGET_IP"
    fi
}

main() {
    [ -z "$MAP_FILE" ] && echo "用法: $0 <映射文件>" && exit 1

    check_and_install_local_tools
    validate_map_file

    NET_IFACE=$(get_network_interface)
    [ -z "$NET_IFACE" ] && echo "❌ 无法获取网络接口" && exit 1

    log "扫描局域网中设备..."
    sudo arp-scan --interface="$NET_IFACE" 192.168.12.0/24 > arp_output.txt

    grep -iE "([0-9a-f]{2}:){5}[0-9a-f]{2}" arp_output.txt | awk '{print tolower($2)" "$1}' > mac_ip_list.txt

    while IFS= read -r line || [ -n "$line" ]; do
        echo "$line" | grep -Eq '^#|^$' && continue
        trimmed=$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

        case "$trimmed" in
            *,*) MAC=$(echo "$trimmed" | cut -d',' -f1 | tr '[:upper:]' '[:lower:]')
                  TARGET_IP=$(echo "$trimmed" | cut -d',' -f2)
                  ;;
            *)   MAC=$(echo "$trimmed" | awk '{print tolower($1)}')
                 TARGET_IP=$(echo "$trimmed" | awk '{print $2}')
                 ;;
        esac

        MATCHED_IPS=$(grep "$MAC" mac_ip_list.txt | awk '{print $2}')
        IP_COUNT=$(echo "$MATCHED_IPS" | wc -l)

        if [ "$IP_COUNT" -eq 0 ]; then
            echo "⚠️ 未找到在线设备: $MAC"
            continue
        fi
        if [ "$IP_COUNT" -gt 1 ]; then
            echo "⚠️ 多个 IP 匹配到 $MAC，使用第一个"
        fi

        CUR_IP=$(echo "$MATCHED_IPS" | head -n1)

        remote_install_network_tools "$CUR_IP"
        configure_static_ip_remote "$MAC" "$TARGET_IP" "$CUR_IP"
    done < "$MAP_FILE"

    echo "✅ 所有设备配置完成"
}

main
