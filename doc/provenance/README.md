# 源码来源与公开范围

ESP32-AirSense 基于 [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) commit `7e69845d818553ac045efbcde746b22bef6eecf6`，保留上游 MIT 许可证及文件头版权。本项目增加微雪 V1 空气仪、SCD41 / SFA40、界面、按键、HA 分钟接口、自动主题与 AirDock 60 结构。

本仓库从 2026-11-02 的开发源码快照建立独立历史，未复制原开发仓库的 `.git`、个人设备部署记录、私人配置、Flash 备份和历史 ZIP。内部构建身份仍为 `waveshare-air-monitor-1.8-v1`，产物名仍为 `xiaozhi.bin`，项目展示名更改不改变协议或 OTA 身份。

公开内容包括源码、固定依赖清单、字体原文件及许可证、通用 HA 配置、必要使用文档和原创结构模型。厂商硬件资料改用[官方链接](../hardware/README.md)，第三方资源仍遵守[各自许可](../../THIRD_PARTY_NOTICES.md)。AirDock 使用的旧 R 编号 helper 和冻结的 R8 接口模型是当前生成链的输入，不是整套旧开发历史。

`dependencies.lock` 约束组件，板型说明记录固定 SDK；编译产物与生成依赖不进入 Git。测试与实机结果须注明对应 commit、环境和范围，源码可构建不等于所有设备已完成验收。
