# Waveshare Air Monitor 1.8 V1

空气检测仪专用板型，基于微雪 **ESP32-S3-Touch-AMOLED-1.8 初版 / V1**，不适用于 V2。屏幕 368×448，16 MB Flash、8 MB PSRAM。SCD41（0x62）与 SFA40（0x5D）共用 GPIO15 SDA、GPIO14 SCL，复用原板已创建的 I²C 总线。

板型身份为 `waveshare-air-monitor-1.8-v1`，构建入口为 `custom/waveshare-air-monitor-1.8-v1`。`config.h` 直接复用原初版引脚配置；没有修改原 V1 的板型身份或接线。

## 接线

| 初版板卡焊点 | 信号 | 两个传感器模块 |
| --- | --- | --- |
| TP4 | VCC3V3，受 PMIC 管理的 3.3 V | VCC |
| TP3 | GND | GND |
| TP7 | GPIO14 / SCL | SCL |
| TP8 | GPIO15 / SDA | SDA |

按官方原理图的 TP 编号和模块丝印焊接，不按照片左右方向接线。**TP2 是 VBUS，不是 3.3 V。** 两模块必须确认支持 3.3 V 供电和 3.3 V I²C 电平；转接板的稳压、上拉和电平转换设计以实际商品为准。初版板上已有约 2.2 kΩ 上拉，不盲目再加上拉。短线、共地；USB 5 V 给板子供电，车载 12 V 不接扩展焊点。

TP4 在 PMIC 真正关机后应随受控电源轨关闭；熄屏时检测继续。USB 关机后的实际电源轨、电流和再唤醒行为仍需实物验证。

依据：[初版官方原理图](https://files.waveshare.com/wiki/ESP32-S3-Touch-AMOLED-1.8/ESP32-S3-Touch-AMOLED-1.8.pdf)、[AXP2101 数据手册](https://files.waveshare.com/wiki/common/X-power-AXP2101_SWcharge_V1.0.pdf)。

## 运行方式

- 浅绿色主页显示 CO₂（ppm）、甲醛（ppb）和 SCD41 温湿度；左右滑动切换历史和设置。读数无效显示破折号，预热 / 稳定 / 过期分别标识。SCD41 约 5 秒更新，SFA40 约 1 秒读取。
- 最近30分钟记录在RAM中，5秒一格、每指标360格；断电后重新记录，不在每次采样时写Flash。
- BOOT只亮屏回主页。PWR短按亮灭屏，检测继续；稳定按住3秒请求正常关机，6秒PMIC硬关机作为后备。正常关机等待采样/音频退出及偏好保存；任务或总线阻塞时1.2秒超时断电，可能丢失最后一次未保存设置。
- 启动已按住的键需先释放；普通按键没有配网、音频测试、清配置快捷操作。
- 无Wi-Fi或连接超时仍保持仪表。配网从设置/详情发起，必须在设备上确认；30秒过期或取消均不执行。
- 保留点击语音及唤醒功能；设置可关闭唤醒、采集及远程语音播放；本地提示音保留。语音工具读取快照，不同步采样。离线不提供联网语音。
- 关闭在线固件安装和在线语音资源替换，升级使用本板型完整构建包；避免普通小智固件覆盖及资源下载与关机冲突。
- 默认USB供电；未知电池规格时禁用主电池及备用电池充电，不沿用原板充电参数。

设置提供日间 / 夜间 / 自动主题、分别保存的亮度、“减少动态”和语音开关。自动模式按 HA 家庭位置的日出日落切换，位置从已鉴权、已确认的分钟上传响应获取并保存到 NVS，UTC 复用上传端的 HTTP Date 校时。选择“自动”后，首次成功上报取得有效位置与时间才开始自动判断；同次开机断网仍按单调时钟计算，断电重启后需重新校时。未取得位置或时间时保持当前主题，不影响手动选择。旧配置保留原先的日间或夜间模式。

浓度提醒保留首页状态、读数颜色、阈值及提示音设置，不再弹窗、抢占对话或唤醒屏幕；每轮可选提示音最多一次，遵守静音、忙碌与关机保护。详情页显示数据年龄、SCD41 自动校准 ASC 状态及配网 / 激活信息。不主动改写 ASC，不执行强制 400 ppm 校准。

SFA40 按原厂协议换算：HCHO = raw × 0.1 ppb；raw=100 表示 10 ppb。先检查完整数据包 CRC，再按传感器状态区分预热、稳定参考值与规格内数据；温湿度统一使用 SCD41。超过 15 秒 / 5 秒没有有效新值时，分别标记 CO₂ / HCHO 过期。详情中的通信、就绪和额定条件状态分别保留，不把断线当成零浓度。

SFA40 冷启动后前约 1 分钟不输出有效甲醛读数，主页显示 `—` / “预热中”；约 1–10 分钟可显示参考读数并标记“稳定中”，约 10 分钟后达到标称规格。以实际返回的状态位为准，不以 MCU 开机计时替代。应保持连续供电观察；反复断电会重新进入预热。原厂地址为 `0x5D`，卖家说明中的 `0x5B` 不能直接作为修改固件地址的依据。

上电、MCU 重启及连续三次读数传输或 CRC 失败后，先停止 SFA40 测量并等待至少 25 ms，再明确发送启测命令；运行中的传感器不能直接重复执行启测命令。空闲设备也可能返回通过 CRC 的数据，不能以“可读”代替启测。若启测通信失败，退回停止步骤重试，避免永久卡在启测重试。正常预热帧不会触发重启，也不使用会影响同总线其他设备的通用软复位。

在“设置 → 传感器与连接”中查看 SFA40 的连接、预热、稳定状态及最近数据更新时间。预热期的零值不能当作有效浓度。

本板支持基本小智语音和 `self.air_quality.read` 快照查询。语音配网请求只能产生待确认操作，不能替代设备上的触摸确认。应用内的 BOOT 操作不进入配网或音频测试；网络、激活、配网和语音关闭状态均有独立入口门槛。

## 构建

### HA 分钟上报配置

本板的 `air_ha_*` 模块每 60 秒汇总实际新样本的平均、最高、最低和数量，独立 HTTPS 任务上传 [HA v2 接口](../../../../homeassistant/README.md)。SCD41 温湿度与 CO₂ 约 5 秒采集，SFA40 甲醛约 1 秒采集；没有有效数据的字段为 null。采集线程不执行网络或 JSON 操作。HA 看板按原采样时间长期保存分钟记录，停车断电不采集、不补零。

在根目录创建私有 `.air-ha/credentials.json`，权限设为 `0600`（目录 `0700`），内容为：

```json
{
  "endpoint": "https://ha.example.com:8123/api/air_monitor/ingest",
  "device_id": "air_monitor_01",
  "upload_key": "替换为该设备专属上传密钥"
}
```

地址为示例，须替换为自己的 HTTPS 入口。上传密钥使用 32–256 个 URL 安全字符，建议用 `python3 -c 'import secrets; print(secrets.token_hex(32))'` 生成；将同一密钥的 SHA-256 摘要登记到自己的 HA。先执行 `mkdir -p .air-ha && chmod 700 .air-ha`，编辑配置后执行 `chmod 600 .air-ha/credentials.json`。不要把命令输出或配置文件提交到 Git。

CMake 经校验生成 `build/generated/air_ha/air_ha_credentials.h`，不输出密钥。私有配置与生成物均不进入 Git；构建产物包含设备凭据，不应直接公开分发。公开固件必须在无私有配置的干净源码目录重新构建；不要只删除配置文件后打包旧的 BIN。

缺少配置时仍可构建，日志明确显示 HA 上传禁用；非 HTTPS、无效设备名／密钥及宽松文件权限会使配置阶段失败。

分钟队列只放 RAM，最多 512 条（约 8 小时 32 分钟），满时丢弃新分钟并记日志，保留等待确认的旧记录。失败从 5 秒指数退避到 5 分钟并加最多 1 秒抖动，联网恢复后立即尝试。最多 16 条一批，成功补传后间隔 2 秒。首次编码后冻结批次内容，只有完整且设备／启动会话／序号匹配的 ACK 才释放缓存；响应丢失时原样重试，由 HA 去重。

上传时钟使用目标 HTTPS 响应的 UTC Date 和本次启动的单调时间，独立于小智系统时区；未取得有效 UTC 前保留队列，校准后可还原本次启动的离线采样时间。每小时重新校准，重试中的报文不重写时间。连接使用 ESP 证书包验证证书链和主机名，不跟随跳转。可控关机仅尽力上传尾段，不延长原有 1.2 秒关机上限；突然断电、重启或关机超时会丢失仍在 RAM 的未上传记录，不提供跨重启补传。

### 编译入口

固定基线：小智 `7e69845d818553ac045efbcde746b22bef6eecf6`，加空气仪修改；ESP-IDF `9a97f6c54ec638111ce55cd36581b3c192f15207`（release/v6.1）。原基线验证使用 Python 3.12.14，本次 HA 功能验证使用 Python 3.12.2。需要 ESP-IDF 所需的 Python、CMake、Ninja、Node / npm，及 `assets/` 中锁定的字体工具；组件解析以 `dependencies.lock` 为准。

在源码目录外准备 SDK，之后回到源码根目录运行：

```sh
git clone --branch release/v6.1 https://github.com/espressif/esp-idf.git ../esp-idf
git -C ../esp-idf checkout 9a97f6c54ec638111ce55cd36581b3c192f15207
git -C ../esp-idf submodule update --init --recursive
bash ../esp-idf/install.sh esp32s3
source ../esp-idf/export.sh
```

已经准备好上述环境时直接构建：

```sh
bash scripts/build_air_monitor.sh
```

脚本在 `.air-font-tools/` 安装锁定的 FontTools 4.56.0 和 lv_font_conv 1.5.3，调用官方 `build.py`。首次安装工具及组件需要联网。已经准备字体工具时，也可设置 `AIR_FONT_PYTHON`、`AIR_FONT_CONVERTER` 后直接运行官方入口：

```sh
python scripts/build.py custom/waveshare-air-monitor-1.8-v1 \
  --name waveshare-air-monitor-1.8-v1 --language zh-CN
```

应用输出为 `build/xiaozhi.bin`，合并镜像为 `build/merged-binary.bin`，刷写清单为 `build/flash_args` / `build/flasher_args.json`。其他板型构建会改变同一个 `build/`，打包前必须重新确认本板身份和 `esp32s3` 目标。不要手改生成配置或组件源码。

字体源与许可证在`assets/fonts/`；生成C进入`build/generated/air_fonts/`，不手改生成文件。新增文案需补入`assets/ui_strings.json`并运行字形检查。默认8MiB PSRAM使用1MiB基础LVGL池，禁用本板不需要的扩池及大图缓存，保留20行RGB565 DMA条。

本板启用每次启动的应用镜像校验。为避免 Wi-Fi 管理锁、ESP 事件循环与 LVGL 互相等待，Wi-Fi 通知通过独立任务投递；待处理通知最多六类，同类保留最后一次状态。`cmake/air_wifi_override.cmake` 只在本板构建中生成锁定依赖的 `NotifyEvent` 替换副本；原 `managed_components/` 不修改。生成器严格校验上游文件 SHA256，依赖变化时停止构建，需重新审查。该桥接不改变 HTTP 配网处理及 Start / Stop 可能等待网络请求结束的行为。

## 主机验证

```sh
python -m unittest discover -s scripts/tests -v
AIR_FONT_CONVERTER="$PWD/.air-font-tools/npm/node_modules/lv_font_conv/lv_font_conv.js" \
  .air-font-tools/python/bin/python -m unittest scripts.tests.test_generate_air_monitor_fonts -v
cmake -S tests/air_monitor -B build-host/air-monitor -DAIR_UI_PREVIEW=ON
cmake --build build-host/air-monitor -j8
ctest --test-dir build-host/air-monitor --output-on-failure
```

UI 主机验证依赖先完成本板构建、解析 LVGL 9.5 和生成字体；使用支持 C++23 的主机 C++ 编译器。若只运行不含界面的测试，可省略 `-DAIR_UI_PREVIEW=ON`。`test_view <已有目录>` 输出原生 368×448 PPM 预览，数据仅在测试中注入。它还通过真实 LVGL 指针输入验证反向拖动、滑杆不翻页和设置边缘翻页。字体测试需使用安装了固定 FontTools 的 Python 和真实 converter；跳过项不能当作已验证。

测试覆盖 CRC / 换算 / 状态、数据过期及趋势缺口、采样恢复时序、按键武装及长按、存储错误、真实 Wi-Fi 父类恢复路径和实际 LVGL 控件。测试中的平台替身只用于主机验证，不编入量产传感器路径。

## 刷写

完整备份原来的 16 MB Flash，保存校验值并核对旧分区；不要先擦全片。交付包的分段清单包含引导、分区、OTA 选择信息、资源和应用，在固件目录中可用 esptool 5.6.0 执行：

```sh
python -m esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX write-flash @flash_args
```

端口改为实物识别到的端口。分段清单不主动写 NVS，但旧配置兼容性仍取决于原分区和内容，不能保证原激活状态直接沿用。合并镜像从 `0x0` 写入会影响中间填充范围内原有配置；仅应用文件则需另外确认活动 OTA 分区、启动选择及资源兼容，不能默认固定写 `0x20000`。

## 验证边界

成功编译、主机测试和原生渲染不等于实机验证。刷机前备份完整Flash并核对分区；最终以交付说明的固件SHA256和测试记录为准。SCD41峰值电流、装壳自热、SFA40材料释放干扰、USB关机电源轨/持续长按再唤醒，以及语音/重连/触摸/双传感器并发性能需要真实板验证。没有硬件数据时不承诺固定帧率或阳光下可读性。

GPIO0在复位时拉低会进入ROM下载模式，这是硬件行为；应用无法屏蔽。正常关机断开的是受控电源轨，USB插头侧可能仍有PMIC/充电相关电流；无电池拔USB会立即失电。
