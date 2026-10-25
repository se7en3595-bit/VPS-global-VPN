#!/bin/bash
# 节点出口与连通性自动验证检测脚本

echo "=== 1. 验证韩国网关出口 ==="
KR_OUT=$(curl -s --max-time 10 -x socks5h://gwuser_kr:"${SOCKS_PASS_KR:-<YOUR_CUSTOM_PASSWORD_KR>}"@127.0.0.1:10808 https://ipinfo.io/json || true)
if [ -n "$KR_OUT" ]; then
    echo "$KR_OUT" | grep -E '"ip"|"country"|"region"|"city"|"org"'
else
    echo "韩国网关 (127.0.0.1:10808) 连接失败或超时"
fi

echo ""
echo "=== 2. 验证日本网关出口 ==="
JP_OUT=$(curl -s --max-time 10 -x socks5h://gwuser_jp:"${SOCKS_PASS_JP:-<YOUR_CUSTOM_PASSWORD_JP>}"@127.0.0.1:10810 https://ipinfo.io/json || true)
if [ -n "$JP_OUT" ]; then
    echo "$JP_OUT" | grep -E '"ip"|"country"|"region"|"city"|"org"'
else
    echo "日本网关 (127.0.0.1:10810) 连接失败或超时"
fi

echo ""
echo "=== 3. 验证 3X-UI 聚合订阅输出 ==="
SUB_URL="https://127.0.0.1:2096/${SUB_PATH:-<YOUR_SUB_PATH>}/${SUB_TOKEN:-<YOUR_CLIENT_SUB_TOKEN>}"
echo "请求订阅端点: $SUB_URL"
SUB_CONTENT=$(curl -s -k --max-time 10 "$SUB_URL" || true)
if [ -n "$SUB_CONTENT" ]; then
    echo "解密后节点列表预览:"
    echo "$SUB_CONTENT" | base64 -d 2>/dev/null | grep "^vless://" || echo "未能解析到 VLESS 节点链接"
else
    echo "订阅端点请求失败"
fi
