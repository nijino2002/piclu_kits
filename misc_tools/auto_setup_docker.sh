#!/bin/sh

PROXY_ADDR="http://192.168.12.232:7890"

echo "[+] 配置系统代理：$PROXY_ADDR"

grep -q "^http_proxy=" /etc/environment 2>/dev/null || echo "http_proxy=$PROXY_ADDR" >> /etc/environment
grep -q "^https_proxy=" /etc/environment 2>/dev/null || echo "https_proxy=$PROXY_ADDR" >> /etc/environment

export http_proxy=$PROXY_ADDR
export https_proxy=$PROXY_ADDR

echo "[+] 修改 APT 软件源为 HTTPS"
sed -i 's|http://|https://|g' /etc/apt/sources.list
if [ -d /etc/apt/sources.list.d ]; then
  for f in /etc/apt/sources.list.d/*.list; do
    if [ -f "$f" ]; then
      sed -i 's|http://|https://|g' "$f"
    fi
  done
fi

echo "[+] 更新 APT 软件源"
apt-get update

echo "[+] 安装 Docker"
curl -fsSL https://get.docker.com | sh

echo "[+] 配置 Docker 镜像加速（可选）"
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<EOF
{
  "registry-mirrors": ["https://dockerproxy.com"]
}
EOF

systemctl daemon-reload
systemctl restart docker

echo "[+] 将当前用户加入 docker 用户组，避免每次使用 sudo"
usermod -aG docker "$USER"

echo "[+] 设置完成！系统将重启，重启后请重新登录以生效用户组更改。"
sleep 5
reboot
