#!/usr/bin/env python3
"""
3X-UI SQLite 数据库补丁与配置微调脚本

功能说明：
1. 放宽 3X-UI 面板内置 Reality 入站的客户端版本校验限制（minClientVer, maxClientVer, maxTimediff）
2. 确保 shortIds 中包含空字符串以增强兼容性
"""

import sys
import sqlite3
import json
import os

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else '/etc/x-ui/x-ui.db'

if not os.path.exists(DB_PATH):
    print(f"错误: 数据库文件不存在: {DB_PATH}")
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

try:
    cursor.execute('SELECT id, stream_settings FROM inbounds')
    rows = cursor.fetchall()
    updated_count = 0

    for row in rows:
        inbound_id, stream_settings_str = row
        if not stream_settings_str:
            continue
        stream_settings = json.loads(stream_settings_str)
        if 'realitySettings' in stream_settings:
            reality_settings = stream_settings['realitySettings']
            reality_settings['minClientVer'] = '0.0.0'
            reality_settings['maxClientVer'] = '255.255.255'
            reality_settings['maxTimediff'] = 0
            if 'shortIds' in reality_settings:
                if '' not in reality_settings['shortIds']:
                    reality_settings['shortIds'].append('')
            else:
                reality_settings['shortIds'] = ['']
            cursor.execute(
                'UPDATE inbounds SET stream_settings=? WHERE id=?',
                (json.dumps(stream_settings), inbound_id)
            )
            updated_count += 1

    conn.commit()
    print(f"成功: 已更新 {updated_count} 个 Reality 入站配置。")
except Exception as e:
    print(f"更新失败: {e}")
    sys.exit(1)
finally:
    conn.close()
