#!/bin/bash
set -e

# 解析 VPN 目标服务器 IP 与端口
REMOTE_HOST=$(grep -E "^remote " /etc/openvpn/client.ovpn | head -n 1 | awk '{print $2}')
REMOTE_PORT=$(grep -E "^remote " /etc/openvpn/client.ovpn | head -n 1 | awk '{print $3}')

# 配置 iptables 强制防护（Kill Switch）
iptables -F
iptables -X
iptables -P OUTPUT DROP
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -o tun+ -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -p udp -d "${REMOTE_HOST}" --dport "${REMOTE_PORT}" -j ACCEPT
iptables -A OUTPUT -p tcp -d "${REMOTE_HOST}" --dport "${REMOTE_PORT}" -j ACCEPT

# 启动 OpenVPN 客户端
openvpn --config /etc/openvpn/client.ovpn --daemon ovpn_proc

# 启动保活看门狗进程
(
  sleep 10
  while true; do
    if ! pgrep -f ovpn_proc > /dev/null; then
      exit 1
    fi
    # 周期性检测数据通道真实连通性
    curl -s --interface tun0 --max-time 5 https://api.ipify.org > /dev/null || true
    sleep 30
  done
) &

# 启动局部 SOCKS5 代理服务
exec microsocks -i 0.0.0.0 -p 1080 -u "${GATE_USER}" -P "${GATE_PASS}"
