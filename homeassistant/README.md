# HA 空气仪分钟接口与看板

最终方案：设备保持原来的快速采集，每 60 秒汇总并上传一条；**一分钟记录长期保留**，在 HA 内查看平均、最高、最低曲线。停车断电没有数据，不补零、不生成停车记录。无需手机 App 或 CSV 导出。

本目录提供 HA 侧集成、看板和上传契约；AIR V1 固件已接入分钟累积与独立 HTTPS 上传任务，配置与测试见[板型说明](../main/boards/custom/waveshare-air-monitor-1.8-v1/README.md)。刷写及车载实际采集仍需实机验收。

## 部署文件

- `custom_components/air_monitor/` → `/config/custom_components/air_monitor/`
- `www/air-monitor-minute-history.js` → `/config/www/air-monitor-minute-history.js`
- `dashboards/air-monitor.yaml` → `/config/dashboards/air-monitor.yaml`

现有 `configuration.yaml` 增加：

```yaml
air_monitor:
  devices: !include air_monitor_devices.yaml
  stale_after: 120
```

设备映射 `/config/air_monitor_devices.yaml`：

```yaml
air_monitor_01:
  name: 空气检测仪
  key_sha256: <32字节安全随机密钥的64位SHA-256摘要>
```

**根据自己的资源模式配置**：使用 storage 模式时，在 HA 设置→仪表盘→资源中添加下面的 JS URL，类型为 JavaScript 模块。原本使用 YAML 资源模式时，将下面内容追加到 `lovelace.resources`。不要切换全局资源模式或覆盖已有资源：

```yaml
- url: /local/air-monitor-minute-history.js?v=2
  type: module
```

在现有 `lovelace.dashboards` 映射追加：

```yaml
air-monitor:
  mode: yaml
  title: 空气检测
  icon: mdi:air-filter
  show_in_sidebar: true
  require_admin: false
  filename: dashboards/air-monitor.yaml
```

在 HA OS 环境执行 `ha core check`，其他安装方式使用对应的配置检查入口，通过后重启 Core。为每个设备单独生成密钥，例如 `python3 -c 'import secrets; print(secrets.token_hex(32))'`，将密钥字符串的 SHA-256 十六进制摘要写入上述设备映射，原始密钥只放设备私有构建配置。修改摘要并重启可撤销或轮换；上传密钥不授予 HA 管理权限，但成功上传的响应会返回 HA 家庭经纬度，见下方自动主题说明。私有文件设为 0600，不写入 Git、日志或公开问题。

## 上传协议 v2

`POST https://ha.example.com:8123/api/air_monitor/ingest`

域名和端口是占位示例，替换为自己的 HA HTTPS 入口或反向代理地址；接口复用现有 HA HTTP 服务，不必另开一个服务端口。固件校验证书和主机名，不能把明文 HTTP 或不受信任证书当作可用替代。

```text
Content-Type: application/json
X-Air-Monitor-Device: air_monitor_01
Authorization: Bearer <设备专属上传密钥>
```

下面是协议示例，不是实测数据：

```json
{
  "schema_version": 2,
  "device_id": "air_monitor_01",
  "session_id": "boot-3f2b8e6d",
  "records": [{
    "seq": 1,
    "period_start": "2026-10-24T08:00:00Z",
    "sampled_at": "2026-10-24T08:00:59Z",
    "uptime_ms": 60000,
    "clock_quality": "synced",
    "co2_ppm": {"mean": 800, "min": 650, "max": 1100, "count": 12},
    "hcho_ppb": {"mean": 20, "min": 10, "max": 35, "count": 60},
    "temperature_c": {"mean": 24.5, "min": 24, "max": 25, "count": 12},
    "humidity_pct": {"mean": 45, "min": 44, "max": 46, "count": 12}
  }]
}
```

- 正常每 60 秒汇总、上传一次，通常每次一条；网络恢复时可批量补传。HA 接口不会自行驱动设备上传，节奏由固件任务实现。
- SCD41 的 CO₂／温湿度约每 5 秒新值，一分钟最多约 12 组；SFA40 约每秒读取，最多约 60 组。只累积**新且有效**样本，不能把重复快照或本机 5 秒历史格当新采样。
- 每字段为 `{mean,min,max,count}` 或 null。没有有效采样用 null，不用零，不硬凑样本数。数值须有限、`min <= mean <= max`，count 为 1–100000 的整数。CO₂ 400–5000 ppm、甲醛 0–1000 ppb、温度 −10–60 °C、湿度 0–95%。固件还应核对 ready、CRC、within_spec、环境条件与新鲜度。
- period_start 是本段第一次实际采样时间，sampled_at 是最后一次实际采样时间；都带时区，间隔 0–60 秒。正常是完整一分钟，已成功上传的不足一分钟尾段也保存。突然断电前仍在 RAM 中的尾段无法保证保存；可控关机可尽力提前上传。
- sampled_at 接受 2020 年之后至接收时间未来 30 秒的时间。未校时必须 `clock_quality: "unsynced"`、两个绝对时间都为 null，保留 uptime_ms；不能虚构采样日期。未校时记录保存但不能在绝对时间曲线上定位。
- device_id／session_id 为 1–64 个英文字母、数字、下划线或连字符，首字符为字母或数字。建议设备 ID 只使用小写字母、数字、下划线。每次启动生成新的随机 session_id，seq 会话内递增。seq、uptime_ms 为 0 至 2⁶³−1 的 JSON 整数。
- 信封／记录须恰好包含上述字段。每批 1–100 条、64 KiB；每设备最多 60 请求／分钟（留给补传与重试，不是建议上传频率），正文超时 10 秒。旧的逐样本 v1 协议不再接受。

提交后响应：`schema_version: 2`、device_id、session_id、`accepted: [seq...]`、inserted、duplicates、current_updated。设备只释放 accepted 对应的缓存。响应丢失后原样重试；设备＋会话＋序号相同即去重，内容不同返回 409 并整批回滚。

400/413/415 修正请求；401 核对密钥；408/429/503 或网络故障退避后原样重试。不要给冲突样本临时改序号绕过 409。

## 永久分钟存储与当前实体

`/config/.storage/air_monitor.sqlite3` 的 `minute_records` 独立表保存原采样时间、接收时间、会话／序号、每分钟四项统计，不自动清理。没有永久保存每秒原始样本，也不直接写 HA Recorder 内部表。旧补传按原时间保存，可出现在专用分钟看板中；只用新鲜且更新的记录推进当前值，同会话序号也须增加。

实体为 `sensor.air_monitor_01_co2`、`hcho`、`temperature`、`humidity`（后面三者也使用同一 sensor 前缀）及 `binary_sensor.air_monitor_01_online`。传感器当前值是最近一段的**分钟平均值**，属性含最高、最低、样本数和时间区间。null 或采样时间超过 120 秒后，至多再等 15 秒刷新就标为不可用。最近成功通信超过 120 秒显示离线。重复补传不延长测量有效性。

本看板直接读独立分钟表，**不受 Recorder 的保留天数或小时汇总粒度影响**。它不修改已有 Recorder 的数据库连接和清理策略，也不要求使用 MySQL；其他 HA 设备的策略保持不变。

## HA 看板

侧栏“空气检测”：`/air-monitor/overview`。四张分钟曲线卡片显示平均线、最高／最低范围及采样数；选择最近一趟、24 小时、7 天、30 天或任意历史时间段（单次最多 31 天）。历史日期可以任意往前选择，并非只能保留 31 天。

“最近一趟”按超过 5 分钟无数据分段、最多取 24 小时，并不声称知道汽车点火状态。绘图在缺失值及超过 90 秒的采样空档处断线，不把停车空档连成连续测量；点选／悬停查看具体一分钟。

看板数据入口 `GET /api/air_monitor/minutes/{device_id}` 使用 **HA 登录权限**，设备上传密钥不能读取。支持 `latest=1` 或秒级 Unix 时间 start/end；最多 31 天、50000 条。此入口供 HA 卡片查看，不提供 CSV 或独立网站。

## 备份与验证

分钟数据不自动删除，但需要纳入备份和磁盘管理。运行中使用 Python SQLite backup API 生成一致快照，不能只拷贝主文件而遗漏 WAL。部署前应备份配置、集成源码和分钟库；已有 Recorder 使用其他数据库时，继续沿用其独立备份方案。

```sh
python3 -m venv /tmp/air-monitor-ha-test
/tmp/air-monitor-ha-test/bin/python -m pip install aiohttp voluptuous
/tmp/air-monitor-ha-test/bin/python -m unittest discover -s homeassistant/tests -v
node --test homeassistant/tests/test_minute_card.mjs
```

测试用真实 SQLite 和 aiohttp 回环 HTTP，仅 HA 视图基类用替身；实际路由鉴权、资源与看板还需目标 HA 验证。真实车载采集与固件上传须实机验收。
## 自动主题的位置来源

成功的 v2 分钟上传 ACK 额外返回 `solar_location`（`latitude` / `longitude`），取自 HA 的家庭位置，仅已通过设备凭据鉴权的上传可获取。固件校验范围后缓存经纬度；无需额外请求，不改变原有 ACK、重试和去重语义。新固件兼容不返回该字段的旧服务端，已有缓存继续使用；首次启用需先更新 HA 集成并重启 HA。
