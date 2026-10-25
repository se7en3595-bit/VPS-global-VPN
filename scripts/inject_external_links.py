#!/usr/bin/env python3
"""
3X-UI 外部订阅节点注入脚本

功能说明：
将独立的家宽 Reality 节点链接动态写入 3X-UI 数据库的 client_external_links 表，
实现由 3X-UI 统一订阅端点自动聚合分发所有机房与家宽节点。
"""

import sys
import sqlite3
import time
import os

DB_PATH = os.environ.get("XUI_DB_PATH", "/etc/x-ui/x-ui.db")
SERVER_IP = os.environ.get("SERVER_IP", "<YOUR_SERVER_IP>")
REALITY_PBK = os.environ.get("REALITY_PUBLIC_KEY", "<YOUR_REALITY_PUBLIC_KEY>")
REALITY_SID = os.environ.get("REALITY_SHORT_ID", "<YOUR_SHORT_ID>")

UUID_KR = os.environ.get("CLIENT_UUID_KR", "<YOUR_CLIENT_UUID_KR>")
UUID_JP = os.environ.get("CLIENT_UUID_JP", "<YOUR_CLIENT_UUID_JP>")
SNI_DOMAIN = os.environ.get("SNI_DOMAIN", "learn.microsoft.com")

if not os.path.exists(DB_PATH):
    print(f"错误: 数据库文件不存在: {DB_PATH}")
    sys.exit(1)

kr_link = (
    f"vless://{UUID_KR}@{SERVER_IP}:38443"
    f"?encryption=none&flow=xtls-rprx-vision&security=reality"
    f"&sni={SNI_DOMAIN}&fp=chrome&pbk={REALITY_PBK}&sid={REALITY_SID}&type=tcp#韩国KT家宽"
)

jp_link = (
    f"vless://{UUID_JP}@{SERVER_IP}:37443"
    f"?encryption=none&flow=xtls-rprx-vision&security=reality"
    f"&sni={SNI_DOMAIN}&fp=chrome&pbk={REALITY_PBK}&sid={REALITY_SID}&type=tcp#日本KDDI家宽"
)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

try:
    now = int(time.time())
    client_id = int(os.environ.get("CLIENT_ID", "1"))

    # 清除旧外部链接
    cursor.execute("DELETE FROM client_external_links WHERE client_id=?", (client_id,))

    # 插入韩国节点
    cursor.execute(
        """
        INSERT INTO client_external_links
        (client_id, kind, value, remark, enable, expiry_time, name_prefix, last_fetch_at, last_fetch_error, sort_index, created_at)
        VALUES (?, 'manual', ?, '韩国KT家宽', 1, 0, '', 0, '', 1, ?)
        """,
        (client_id, kr_link, now)
    )

    # 插入日本节点
    cursor.execute(
        """
        INSERT INTO client_external_links
        (client_id, kind, value, remark, enable, expiry_time, name_prefix, last_fetch_at, last_fetch_error, sort_index, created_at)
        VALUES (?, 'manual', ?, '日本KDDI家宽', 1, 0, '', 0, '', 2, ?)
        """,
        (client_id, jp_link, now)
    )

    conn.commit()
    print("成功: 外部家宽节点已注入 3X-UI 订阅数据库。")
except Exception as e:
    print(f"注入失败: {e}")
    sys.exit(1)
finally:
    conn.close()
