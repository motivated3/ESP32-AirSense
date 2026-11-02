# ESP32-AirSense 文档

适用微雪 ESP32-S3-Touch-AMOLED-1.8 **V1**，SCD41 和 SFA40；不适用于 V2。功能、板型身份及使用限制以当前源码和以下入口为准。

| 内容 | 入口 |
| --- | --- |
| 接线、备份、刷写、按键及读数 | [使用说明](接线与刷写说明.md) |
| SDK、字体工具、HA 私有配置、主机验证 | [板型 README](../main/boards/custom/waveshare-air-monitor-1.8-v1/README.md) |
| 读数颜色阈值与单位 | [颜色分级](浓度读数颜色分级.md) |
| 自动主题、位置数据流和浓度提醒 | [行为说明](自动主题与提醒.md) |
| HA 安装、鉴权与分钟看板 | [HA README](../homeassistant/README.md)、[保存说明](HA端接入与保存说明.md) |
| 官方硬件资源 | [来源链接](hardware/README.md) |
| 60° 屏幕与分舱底座 | [AirDock 60](enclosure/airdock-60/README.md) |
| 源码范围、上游来源 | [来源说明](provenance/README.md) |
| 本轮构建与测试的范围和结果 | [验证记录](验证记录.md) |
| 贡献、验证及第三方许可 | [贡献指南](../CONTRIBUTING.md)、[第三方说明](../THIRD_PARTY_NOTICES.md) |

源码构建、主机测试、屏幕预览、真实测量和装壳温升分别验证。`docs/` 保留上游公共协议和开发文档，不是 V1 空气仪的替代刷写入口。
