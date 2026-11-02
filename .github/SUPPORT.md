# 项目支持与上游账号服务

本仓库主要维护微雪 1.8 寸 AMOLED V1 空气检测仪。接线、构建、空气检测、HA 集成及 AirDock 60 问题请先查看[项目说明](../README.md)和[贡献指南](../CONTRIBUTING.md)，报告可复现步骤并脱敏日志。

本项目不运营小智账号或云服务。以下保留上游账号服务指引；空气检测仪代码问题不应发送给上游账号客服。

## Upstream Account and Device Support

This GitHub repository tracks the open-source XiaoZhi device firmware. Account recovery, device ownership, and cloud-service requests are handled outside the public issue tracker.

## Unbind a Previously Owned Device

If you purchased or received a used device that is still bound to another person's account:

1. Collect the device ID and MAC address using the instructions below.
2. Email [xiaozhi.ai@tenclass.com](mailto:xiaozhi.ai@tenclass.com?subject=Device%20unbinding%20request) with both identifiers.
3. Use an email subject such as `Device unbinding / 解绑设备 - Device ID XXX - MAC address XXX`.

For multiple devices, attach a list containing the device ID and MAC address for each device.

> **Privacy:** Send device IDs and MAC addresses only by email. Do not post them in a public GitHub issue, discussion, screenshot, or log.

### Why Both Identifiers Are Required

- The **MAC address** uniquely identifies the physical device hardware.
- The **device ID** is obtained by asking the AI running on the device. Providing the value reported by the device helps demonstrate that the requester has the device in hand and can operate it.

Together, these identifiers help the support team locate the correct binding record and avoid unbinding the wrong device.

### Find the Device ID

If the device can connect and have a conversation, ask it:

> What is my device ID?

Record the complete value reported by the device. Both the device ID and MAC address are required for the standard unbinding process. If the device cannot have a conversation or does not return a device ID, explain this in the email; the support team may require other proof of possession. Do not guess or substitute a temporary activation code.

### Find the MAC Address

1. Connect the powered-on device to a computer with a data-capable USB cable.
2. Open the device's serial port with a serial terminal. Developers with an ESP-IDF environment can use `idf.py monitor`.
3. Keep the serial terminal open and restart the device so that the complete startup log is captured.
4. Search the log for a line similar to:

   ```text
   wifi:mode : sta (aa:bb:cc:dd:ee:ff)
   ```

5. The value inside the parentheses is the Wi-Fi MAC address to include in the email.

If that line does not appear, search the startup log for `MAC` or `mac_address`. If you still cannot identify it, attach the exact device model and explain the situation in the private email. Do not upload the unredacted startup log to a public GitHub issue because it may contain the MAC address, UUID, Wi-Fi name, and other device information.

## Other Account and Cloud-Service Requests

For verification codes, password recovery, activation, agent configuration, voiceprint, voice cloning, and other cloud services, use the [XiaoZhi AI website](https://xiaozhi.me/).
