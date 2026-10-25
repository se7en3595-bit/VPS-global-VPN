# VPS 混合架构代理网关与 Reality 家宽节点搭建部署全指南

本文档记录了在 Linux 云服务器（Debian 12 / Debian 13）上从零构建一套高可用混合节点网关的完整工程实践。系统将「3X-UI 原生机房节点」与「基于 Docker 隔离的真实住宅 IP（家宽）出口节点」进行深度融合，并通过统一订阅服务对外分发。

文档详细收录了架构设计、环境配置、端到端部署流程、实测核验方法、核心故障排查分析（涵盖 Reality 握手校验失败、抗量子加密冲突、客户端 TUN 路由死锁等深层问题）以及配套自动化脚本。

---

## 一、架构设计与工作原理

### 1. 整体架构拓扑

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

### 2. 双出口机制对比

| 线路类型 | 接入协议 | 监听端口 | 出口网络特征 | 核心用途 |
| :--- | :--- | :--- | :--- | :--- |
| **云端直连线路** | VLESS + TCP + Reality + Vision | 443, 8443 | 云服务商数据中心机房 IP，低延迟、高带宽 | 网页浏览、影音媒体、日常大流量下载 |
| **韩国家宽线路** | VLESS + TCP + Reality + Vision | 38443 | 韩国釜山 Korea Telecom 真实家庭宽带 | 严格风控平台、账号注册、韩区本土服务 |
| **日本家宽线路** | VLESS + TCP + Reality + Vision | 37443 | 日本神奈川 KDDI 真实家庭宽带 | 严格风控平台、日区应用、防机房风控检测 |

---

## 二、环境准备与前置条件

### 1. 硬件与操作系统基准

- **操作系统**：Debian 12 / Debian 13 (x86_64 或 aarch64)。
- **服务器配置**：最低 1 核心 CPU，物理内存大于等于 512MB（若低于 1GB，必须建立 1GB 以上 Swap 分区）。
- **内核特性**：内核需支持并启用 TUN 设备（`/dev/net/tun`）。

### 2. 软件依赖与版本要求

- **容器运行时**：Docker Engine 24.x 及以上，安装 `containerd` 与 `docker-compose-plugin`。
- **Xray 核心版本**：推荐采用 **Xray 26.7.28 稳定版**。实测 Xray 26.10.x 因强制引入抗量子握手与客户端版本限制，会导致主流客户端校验失败。
- **面板管理工具**：3X-UI v3.10.2。
- **基础工具库**：`curl`、`sqlite3`、`python3`、`iptables`、`systemd-timesyncd`。

### 3. 云平台防火墙（安全组）规划

在云控制台（如 Google Cloud VPC、AWS Security Group、阿里云安全组）中放行以下 TCP 端口入站：

- **TCP 443**：3X-UI 主 Reality 节点。
- **TCP 8443**：3X-UI 备用 Reality 节点。
- **TCP 2096**：3X-UI 节点订阅服务（HTTPS）。
- **TCP 2522**：3X-UI 网页后台管理端口。
- **TCP 38443**：独立韩国家宽 Reality 接入端口。
- **TCP 37443**：独立日本家宽 Reality 接入端口。
- **SSH 端口**：远程登录管理端口（如 22 或自定义端口）。

---

## 三、完整搭建与配置步骤

### 步骤 1：系统基础调优与 Swap 内存扩容

若物理内存不足 1GB，执行以下命令建立 1GB Swap 分区，防止构建 Docker 镜像或启动容器时触发 OOM 崩溃：

```bash
# 检查现有 Swap
free -m

# 创建 1GB Swap 镜像文件
fallocate -l 1G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=1024
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile

# 持久化挂载
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# 配置系统时间精准同步
timedatectl set-ntp true
systemctl restart systemd-timesyncd
timedatectl status
```

### 步骤 2：安装 Docker 运行时环境

```bash
apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release sqlite3

# 安装 Docker 官方仓库
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
```

### 步骤 3：安装 3X-UI 面板与 Xray 核心降级适配

1. 部署 3X-UI 面板：

```bash
bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)
```

2. 替换为兼容标准客户端握手的 Xray 26.7.28 核心：

```bash
# 备份原核心
cp -a /usr/local/x-ui/bin/xray-linux-amd64 /usr/local/x-ui/bin/xray-linux-amd64.bak

# 下载并解压 Xray 26.7.28
mkdir -p /tmp/xray-stable && cd /tmp/xray-stable
curl -sL -o Xray-linux-64.zip https://github.com/XTLS/Xray-core/releases/download/v26.7.28/Xray-linux-64.zip
unzip -q Xray-linux-64.zip
cp -f xray /usr/local/x-ui/bin/xray-linux-amd64
chmod +x /usr/local/x-ui/bin/xray-linux-amd64

# 验证核心版本
/usr/local/x-ui/bin/xray-linux-amd64 version
```

3. 修复 3X-UI 数据库参数，放宽客户端版本与握手限制：

可以使用仓库提供的 `scripts/patch_3xui_reality.py` 脚本：

```bash
python3 scripts/patch_3xui_reality.py /etc/x-ui/x-ui.db

# 同步刷新并平滑重启服务
x-ui restart
```

### 步骤 4：构建 Homeline 住宅 IP 网关容器（带防泄漏与自愈）

创建专用工作目录 `/opt/homeline`：

```bash
mkdir -p /opt/homeline/{image,line-kr,line-jp,xray}
```

将仓库中的 `docker/Dockerfile` 和 `docker/entrypoint.sh` 拷贝至 `/opt/homeline/image/`。

构建镜像并运行独立线路容器：

```bash
cd /opt/homeline/image
docker build -t homeline-gw:v2 .

# 启动韩国网关容器（映射至 127.0.0.1:10808）
docker run -d --name vpngw-kr-gateway \
  --cap-add=NET_ADMIN --device /dev/net/tun \
  --restart unless-stopped \
  --dns 8.8.8.8 --dns 1.1.1.1 \
  -v /opt/homeline/line-kr/client.ovpn:/etc/openvpn/client.ovpn:ro \
  -e GATE_USER=gwuser_kr -e GATE_PASS=<YOUR_CUSTOM_PASSWORD_KR> \
  -p 127.0.0.1:10808:1080 \
  homeline-gw:v2

# 启动日本网关容器（映射至 127.0.0.1:10810）
docker run -d --name vpngw-jp-gateway \
  --cap-add=NET_ADMIN --device /dev/net/tun \
  --restart unless-stopped \
  --dns 8.8.8.8 --dns 1.1.1.1 \
  -v /opt/homeline/line-jp/client.ovpn:/etc/openvpn/client.ovpn:ro \
  -e GATE_USER=gwuser_jp -e GATE_PASS=<YOUR_CUSTOM_PASSWORD_JP> \
  -p 127.0.0.1:10810:1080 \
  homeline-gw:v2
```

### 步骤 5：配置独立的 Homeline Xray 服务

为避免与 3X-UI 面板的重载逻辑产生互锁，建立独立的 Xray 实例转发家宽节点。

参考 `config/xray-config.template.json` 替换占位参数生成 `/opt/homeline/xray/config.json`。

下载并部署独立的 Xray 运行实体：

```bash
cp /usr/local/x-ui/bin/xray-linux-amd64 /opt/homeline/xray/xray
chmod +x /opt/homeline/xray/xray
```

配置并启动 systemd 服务（参考 `config/homeline-xray.service`）：

```bash
cp config/homeline-xray.service /etc/systemd/system/homeline-xray.service
systemctl daemon-reload
systemctl enable --now homeline-xray
```

### 步骤 6：利用 3X-UI 聚合全量订阅链接

使用提供的 Python 脚本将两条家宽线路写入 3X-UI 的 `client_external_links` 数据库表中，使默认订阅链接自动包含全量 4 个节点：

```bash
export SERVER_IP="<YOUR_SERVER_IP>"
export REALITY_PUBLIC_KEY="<YOUR_REALITY_PUBLIC_KEY>"
export REALITY_SHORT_ID="<YOUR_SHORT_ID>"
export CLIENT_UUID_KR="<YOUR_CLIENT_UUID_KR>"
export CLIENT_UUID_JP="<YOUR_CLIENT_UUID_JP>"

python3 scripts/inject_external_links.py

# 重启面板生效
x-ui restart
```

---

## 四、验证测试与健康巡检

### 1. 本地 SOCKS5 隔离出口真实性测试

在 VPS 本地直接探测两个网关端口，核实返回的 IP 归属地与 ASN：

```bash
# 测试韩国线路出口（必须返回真实运营商宽带 IP）
curl -s -x socks5h://gwuser_kr:<YOUR_CUSTOM_PASSWORD_KR>@127.0.0.1:10808 https://ipinfo.io/json

# 测试日本线路出口（必须返回真实运营商宽带 IP）
curl -s -x socks5h://gwuser_jp:<YOUR_CUSTOM_PASSWORD_JP>@127.0.0.1:10810 https://ipinfo.io/json
```

核验指标：

- 出口 IP 绝不能是 VPS 宿主自身 IP。
- `org` 属性不得带有 Hosting、Data Communication 或 Cloud 标记，需确认为电信运营商民用宽带。

也可使用提供的自动化检测脚本：

```bash
bash scripts/check_health.sh
```

### 2. 订阅服务输出校验

执行以下命令，测试 3X-UI 聚合下发的 Base64 订阅内容：

```bash
curl -s -k https://127.0.0.1:2096/<YOUR_SUB_PATH>/<YOUR_CLIENT_SUB_TOKEN> | base64 -d
```

预期输出结果包含 4 条以 `vless://` 开头的完整节点信息。

---

## 五、踩坑记录与排错指引（Troubleshooting）

### 故障 1：客户端持续报错 `reality verification failed`

#### 现象描述

客户端握手阶段立即中断，弹出警告：`reality verification failed`。

#### 根因分析

1. **抗量子密钥交换强制拦截**：Xray 26.10.x 服务端在 Reality 传输层默认启用了抗量子特性，强制要求客户端 ClientHello 携带 `X25519MLKEM768` 算法扩展。目前手机端及主流桌面客户端普遍采用标准 `X25519`，握手协商被服务端判定不合规。
2. **触发回落机制**：服务端拒绝握手后，自动将连接透传回退至目标伪装网站（`learn.microsoft.com`）。客户端收到了微软真实的 TLS 证书，检测到缺少 Reality 专有临时签名，抛出校验失败。
3. **客户端版本规则限制**：Xray 新版默认内置 `minClientVer = 26.3.27`，第三方客户端版本标识比对失败即拒绝连接。

#### 解决办法

1. 将 Xray 核心降级至全面兼容标准握手的成熟版本 **Xray 26.7.28**。
2. 在服务端入站配置中显式声明：
  - `minClientVer`: `"0.0.0"`
  - `maxClientVer`: `"255.255.255"`
  - `shortIds`: 包含专用 ID 并在末尾保留空字符串 `""`。
3. 伪装域名统一采用对国内网络直连通畅的微软官方学习站点：`learn.microsoft.com:443`。

---

### 故障 2：客户端提示 `x509: certificate is valid for ... not itunes.apple.com`

#### 现象描述

客户端报错证书域名不匹配，明确提示收到的是 `www.apple.com` 的证书，而不是配置中指定的 `itunes.apple.com`。

#### 根因分析

客户端节点链接中的 SNI 伪装域名参数与服务端实际转发目标 Dest 存在差异。当发生回落时，真实服务器下发的证书域名无法匹配客户端期望的 SNI。

#### 解决办法

严格统一服务端与客户端的伪装参数：

- 服务端目标 `dest`：`learn.microsoft.com:443`
- 服务端名称 `serverNames`：`["learn.microsoft.com"]`
- 客户端连接参数 `sni`：`learn.microsoft.com`

---

### 故障 3：客户端开启连接后显示连接超时、流量全为 0

#### 现象描述

从订阅拉取节点成功，但点击测速显示红标超时，入站流量统计没有任何增长。

#### 根因分析

客户端（如 Karing）开启了 TUN 虚拟网卡模式，在代理通道未正式连通前，该网卡在 Windows 路由表中注入了一条全网默认路由。当客户端自身向 VPS 发起连接请求时，数据包被强行截留回送至虚拟网卡自身，造成死锁闭环。

#### 解决办法

1. 在系统托盘中彻底退出并杀除客户端进程。
2. 重启客户端，确保在连接建立前关闭 TUN 虚拟网卡开关。
3. 导入标准节点链接，单点激活后再开启代理。

---

### 故障 4：Docker 无法创建执行进程，报错 `no space left on device`

#### 现象描述

在构建镜像或启动容器时，系统提示存储空间已满，但物理磁盘 `df -h /` 仍有充足可用容量。

#### 根因分析

系统 `/tmp` 目录挂载为独立的 `tmpfs` 内存文件系统（容量通常仅有数百兆）。若此前运行过抓包程序（如 `tcpdump` 生成了大型 `.pcap` 文件）且未及时清理，会占满 `/tmp`，导致 `runc` 运行时因无法创建临时套接字而失败。

#### 解决办法

```bash
# 查看 /tmp 占用情况
df -h /tmp

# 查找并清理残留的大体积临时文件与抓包缓存
rm -f /tmp/*.pcap /tmp/*.zip
```

---

### 故障 5：OpenVPN 容器内部域名解析失败（DNS 穿透失效）

#### 现象描述

容器内部隧道已经建立，Ping 外部公网 IP 畅通，但所有域名解析均提示 `connection timed out`。

#### 根因分析

部分云平台（如 Google Cloud）默认下发 `169.254.169.254` 本地链路地址作为实例 DNS。OpenVPN 接管容器默认路由后，该内部网段不可达，导致 DNS 解析全部阻断。

#### 解决办法

在 `docker run` 命令中强制声明公网通用 DNS 解析器：

```bash
--dns 8.8.8.8 --dns 1.1.1.1
```

---

## 六、参考资源与项目出处

1. **家宽出口网关 Skill 仓库**：
  - [free-dam-man/homeline-residential-exit-skill](https://github.com/free-dam-man/homeline-residential-exit-skill)
2. **Project X 核心与协议规范**：
  - [XTLS/Xray-core 官方仓库](https://github.com/XTLS/Xray-core)
  - [REALITY 协议开源实现](https://github.com/XTLS/REALITY)
3. **多协议面板**：
  - [3X-UI (MHSanaei 版)](https://github.com/MHSanaei/3x-ui)
4. **全球边缘节点部署规范**：
  - [se7en3595-bit/cf-global-edge-node-skill](https://github.com/se7en3595-bit/cf-global-edge-node-skill)
5. **公益住宅网络提供方**：
  - [VPN Gate 学术实验项目](https://www.vpngate.net/)
