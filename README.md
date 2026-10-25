# VPS 混合架构代理网关与 Reality 家宽节点部署方案 (VPS-global-VPN)

本项目基于 Debian 12 / Debian 13 云服务器环境，提供一套高可用、生产就绪的混合网络代理网关解决方案。系统融合了「3X-UI 原生机房节点（高带宽、低延迟）」与「基于 Docker 容器隔离的真实住宅宽带（家宽）出口节点（高防风控、本土服务访问）」，并通过 3X-UI 统一订阅端点对外聚合分发。

本仓库已完成全量敏感信息（IP 地址、私钥、UUID、密码、订阅凭证等）的脱敏与参数化封装，提供开箱即用的配置文件模板与运维自动化脚本。

---

## 架构拓扑与设计原理

```text
                               ┌────────────────────────────────────────────────────────┐
                               │                     云服务器 (VPS)                     │
                               │                                                        │
客户端 (Karing / Clash / v2rayN)│  ┌────────────── 3X-UI 服务与订阅 (2096) ─────────────┐│
                               │  │                                                     ││
       ├── TCP 443 / 8443 ────┼─►│ Xray 核心 (26.7.28 兼容版)                            ││
       │   (VLESS Reality)     │  │ └── 直连出站 ───────────────────────► 目标互联网     ││
       │                       │  └─────────────────────────────────────────────────────┘│
       │                       │                                                         │
       │                       │  ┌────────────── Homeline 独立家宽实例 ────────────────┐│
       │                       │  │                                                     ││
       ├── TCP 38443 (韩国) ──┼─►│ 独立 Xray 实例 (37443 / 38443)                       ││
       └── TCP 37443 (日本) ──┼─►│    │                                                 ││
           (VLESS Reality)     │  │    ├── 本地转发 127.0.0.1:10808                     ││
                               │  │    └── 本地转发 127.0.0.1:10810                     ││
                               │  │           │                                         ││
                               │  │           ▼                                         ││
                               │  │    Docker 隔离网关 (OpenVPN + Kill Switch)          ││
                               │  │           │                                         ││
                               │  │           ▼                                         ││
                               │  │    VPN Gate 志愿者住宅网络                          ││
                               │  │           │                                         ││
                               │  │           ▼                                         ││
                               │  │    真实住宅宽带出口 (KT / KDDI ISP) ──► 目标互联网   ││
                               │  └─────────────────────────────────────────────────────┘│
                               └────────────────────────────────────────────────────────┘
```

### 双出口网络特征对比

| 线路类型 | 接入协议 | 监听端口 | 出口网络特征 | 核心用途 |
| :--- | :--- | :--- | :--- | :--- |
| **云端直连线路** | VLESS + TCP + Reality + Vision | 443, 8443 | 云服务商机房 IP，低延迟、高带宽 | 网页浏览、流媒体播放、日常大流量下载 |
| **韩国家宽线路** | VLESS + TCP + Reality + Vision | 38443 | 韩国釜山 Korea Telecom 真实家庭宽带 | 严格风控平台、账号注册、韩区本土服务 |
| **日本家宽线路** | VLESS + TCP + Reality + Vision | 37443 | 日本神奈川 KDDI 真实家庭宽带 | 严格风控平台、日区应用、防机房风控检测 |

---

## 仓库结构说明

```text
VPS-global-VPN/
├── README.md                          # 项目完整介绍与部署指南
├── LICENSE                            # 开源许可证 (Apache-2.0)
├── docker/                            # 家宽出口网关 Docker 隔离镜像
│   ├── Dockerfile                     # Alpine 3.19 + OpenVPN + MicroSocks 运行环境
│   └── entrypoint.sh                  # 容器启动脚本，内置 iptables Kill Switch 与自愈守护
├── config/                            # 核心配置文件模板
│   ├── xray-config.template.json      # 独立 Homeline Xray 服务多入站/多出站配置模板
│   └── homeline-xray.service          # 独立 Xray 的 systemd 服务单元文件
├── scripts/                           # 运维辅助与自动配置脚本
│   ├── patch_3xui_reality.py          # 3X-UI 数据库补丁：放宽 Reality 客户端握手限制
│   ├── inject_external_links.py       # 将家宽 Reality 节点注入 3X-UI 统一订阅
│   └── check_health.sh                # 本地 SOCKS5 出口归属地与订阅端点巡检脚本
└── docs/                              # 工程实践详尽技术文档
    └── vps-hybrid-reality-gateway.md  # 踩坑排错手册、内核调优与全流程排障指引
```

---

## 快速开始

### 1. 前置依赖准备

- **操作系统**：Debian 12 / Debian 13 (x86_64 或 aarch64)
- **硬件配置**：最低 1 核心 CPU，物理内存大于等于 512MB（若低于 1GB，需配置 1GB Swap 分区）
- **内核功能**：支持并启用 TUN 设备（`/dev/net/tun`）
- **防火墙放行**：放行 TCP 443, 8443, 2096, 2522, 38443, 37443 端口

### 2. 部署步骤概览

#### 第一步：安装 Docker 运行时

```bash
apt-get update && apt-get install -y ca-certificates curl gnupg lsb-release sqlite3
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
```

#### 第二步：部署 3X-UI 并适配 Xray 核心

```bash
# 1. 安装 3X-UI 面板
bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)

# 2. 核心版本适配 (建议使用稳定的 26.7.28 避免抗量子校验冲突)
cp -a /usr/local/x-ui/bin/xray-linux-amd64 /usr/local/x-ui/bin/xray-linux-amd64.bak
mkdir -p /tmp/xray-stable && cd /tmp/xray-stable
curl -sL -o Xray-linux-64.zip https://github.com/XTLS/Xray-core/releases/download/v26.7.28/Xray-linux-64.zip
unzip -q Xray-linux-64.zip
cp -f xray /usr/local/x-ui/bin/xray-linux-amd64
chmod +x /usr/local/x-ui/bin/xray-linux-amd64

# 3. 执行数据库补丁
python3 scripts/patch_3xui_reality.py /etc/x-ui/x-ui.db
x-ui restart
```

#### 第三步：构建并运行家宽 Docker 网关

```bash
mkdir -p /opt/homeline/{image,line-kr,line-jp,xray}
cp docker/* /opt/homeline/image/
cd /opt/homeline/image
docker build -t homeline-gw:v2 .

# 放入各自线路的 OpenVPN 配置文件 client.ovpn 到对应目录
# /opt/homeline/line-kr/client.ovpn
# /opt/homeline/line-jp/client.ovpn

# 启动韩国网关容器
docker run -d --name vpngw-kr-gateway \
  --cap-add=NET_ADMIN --device /dev/net/tun \
  --restart unless-stopped \
  --dns 8.8.8.8 --dns 1.1.1.1 \
  -v /opt/homeline/line-kr/client.ovpn:/etc/openvpn/client.ovpn:ro \
  -e GATE_USER=gwuser_kr -e GATE_PASS=<YOUR_CUSTOM_PASSWORD_KR> \
  -p 127.0.0.1:10808:1080 \
  homeline-gw:v2

# 启动日本网关容器
docker run -d --name vpngw-jp-gateway \
  --cap-add=NET_ADMIN --device /dev/net/tun \
  --restart unless-stopped \
  --dns 8.8.8.8 --dns 1.1.1.1 \
  -v /opt/homeline/line-jp/client.ovpn:/etc/openvpn/client.ovpn:ro \
  -e GATE_USER=gwuser_jp -e GATE_PASS=<YOUR_CUSTOM_PASSWORD_JP> \
  -p 127.0.0.1:10810:1080 \
  homeline-gw:v2
```

#### 第四步：部署独立 Homeline Xray 实例

```bash
# 复制二进制与服务单元
cp /usr/local/x-ui/bin/xray-linux-amd64 /opt/homeline/xray/xray
chmod +x /opt/homeline/xray/xray
cp config/homeline-xray.service /etc/systemd/system/homeline-xray.service

# 根据 config/xray-config.template.json 生成 /opt/homeline/xray/config.json 并填入参数
# 启动独立服务
systemctl daemon-reload
systemctl enable --now homeline-xray
```

#### 第五步：聚合订阅下发

```bash
export SERVER_IP="<YOUR_SERVER_IP>"
export REALITY_PUBLIC_KEY="<YOUR_REALITY_PUBLIC_KEY>"
export REALITY_SHORT_ID="<YOUR_SHORT_ID>"
export CLIENT_UUID_KR="<YOUR_CLIENT_UUID_KR>"
export CLIENT_UUID_JP="<YOUR_CLIENT_UUID_JP>"

python3 scripts/inject_external_links.py
x-ui restart
```

---

## 核心故障排错速查

详细排错分析请阅读 [docs/vps-hybrid-reality-gateway.md](docs/vps-hybrid-reality-gateway.md)。

| 故障现象 | 关键根因 | 解决对策 |
| :--- | :--- | :--- |
| `reality verification failed` | Xray 新版强制开启抗量子交换，客户端版本比对拦截 | 降级至稳定版 Xray 26.7.28，并在服务端入站配置中放宽版本范围与短 ID |
| 证书域名与 SNI 不匹配 | 客户端 SNI 与服务端 Reality Dest 目标不一致 | 严格保持服务端 `dest`、`serverNames` 与客户端 `sni` 均为 `learn.microsoft.com` |
| 连接后显示超时流量为 0 | 客户端 TUN 模式引发 Windows 路由回环死锁 | 彻底退出客户端，先关闭虚拟网卡再启动连接 |
| Docker 报 `no space left` | 系统 `/tmp` 临时文件系统被抓包或缓存文件占满 | 清理 `/tmp/*.pcap` 与临时缓存包 |
| OpenVPN 容器内 DNS 解析超时 | 云厂商默认私有 DNS（如 169.254.x.x）在接管默认路由后不可达 | 容器运行时强制指定公网通用 DNS（`--dns 8.8.8.8 --dns 1.1.1.1`） |

---

## 许可证

本项目遵循 [Apache-2.0 License](LICENSE) 协议开源。
