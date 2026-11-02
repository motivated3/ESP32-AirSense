# 参与开发

本项目主要维护微雪 1.8 寸 AMOLED **V1** 空气检测仪。先阅读[板型说明](main/boards/custom/waveshare-air-monitor-1.8-v1/README.md)及[接线与刷写说明](doc/接线与刷写说明.md)，其他上游板型不代表已完成本项目的适配或验收。

## 报告问题

提供板卡版本、源码 commit、构建命令、可复现步骤、预期与实际行为。传感器问题请补充转接板型号、供电、焊点、预热时长和是否装壳；界面问题附屏幕照片或复现步骤。

发布日志或截图前，删除 Wi-Fi 名称和密码、设备标识、MAC、激活码、HA 地址与上传密钥。不要上传完整 Flash 备份、私有配置或含凭据的固件。账号及小智云服务问题请参考[支持范围](.github/SUPPORT.md)。

## 修改范围

- 优先在本板目录解决板级问题，保留公共板型和协议的兼容性。
- 不手改 `build/`、`managed_components/`、生成字体或 `sdkconfig`；从脚本和默认配置修复。
- 新增固定文案时更新 `assets/ui_strings.json` 并检查字形覆盖。
- 更改传感器协议、网络、音频、关机或线程逻辑时，覆盖失败与恢复路径；说明还未验证的真实硬件行为。
- CAD 更改请标明测量值与设计余量，重新生成并检查模型与切片。不要沿用旧 G-code 或把参考图当作已试装成品。

## 本地检查

无需外设的核心主机测试，需要 CMake 和支持 C++23 的编译器：

```sh
cmake -S tests/air_monitor -B build-host/air-monitor
cmake --build build-host/air-monitor -j8
ctest --test-dir build-host/air-monitor --output-on-failure
```

其他主机脚本测试：

```sh
python -m unittest discover -s scripts/tests -v
```

完整 Python / LVGL 测试还依赖组件下载、固定字体工具和生成字体，见[板型主机验证](main/boards/custom/waveshare-air-monitor-1.8-v1/README.md#主机验证)。跳过项或缺依赖不能写成全部通过。涉及固件行为的修改还应完成本板构建并说明实机检查结果。

HA 后端及卡片的独立测试见 [homeassistant/README.md](homeassistant/README.md#备份与验证)。

## 发布边界

`.air-ha/` 只用于自己的部署。公开固件应从没有私有配置的干净源码目录构建，并收集实际固件所用组件、字体和语音模型的许可。不要使用日常开发目录中的已有 BIN、NVS 或全片备份作为公开固件。

现有 GitHub 工作流保留了小智的多板型构建与发布流程；自动板型构建已暂停，手动运行也不会自动准备 AIR 字体工具。首次发布 AIR 前需要单独核对目标、资源、分区及许可，不直接启动全板型公开发布工作流。
