# 第三方来源与许可

根目录 [LICENSE](LICENSE) 保留小智的 MIT 许可证与版权声明。下表区分独立许可的内容；根 MIT 不替代字体、组件、模型或厂商资料自身的许可。

| 范围 | 来源 / 许可 | 仓库内说明 |
| --- | --- | --- |
| 小智基线和本项目修改 | [xiaozhi-esp32 固定版本](https://github.com/78/xiaozhi-esp32/tree/7e69845d818553ac045efbcde746b22bef6eecf6)，MIT；个别文件另有标注的除外 | [LICENSE](LICENSE)、[来源记录](doc/provenance/README.md) |
| 带 Apache-2.0 SPDX 的脚本和驱动 | 保留各文件头部的原作者及来源声明，例如 `scripts/build_default_assets.py`、`scripts/spiffs_assets/spiffs_assets_gen.py` | [Apache-2.0 全文](LICENSES/Apache-2.0.txt) |
| AIR 的 Noto Sans SC、Roboto Condensed 字体 | SIL Open Font License 1.1；固定源文件及哈希见 `assets/fonts.json` | [字体来源](main/boards/custom/waveshare-air-monitor-1.8-v1/assets/README.md)、[Noto 许可](main/boards/custom/waveshare-air-monitor-1.8-v1/assets/fonts/OFL-NotoSansSC.txt)、[Roboto 许可](main/boards/custom/waveshare-air-monitor-1.8-v1/assets/fonts/OFL-RobotoCondensed.txt) |
| gifdec | 原目录的 public-domain 声明 | [原声明](main/display/lvgl_display/gif/LICENSE.txt) |
| AIR 告警提示音 | 本项目代码原创合成，未使用下载音效，按项目许可使用 | [合成来源](main/boards/custom/waveshare-air-monitor-1.8-v1/assets/alert-tone-source.md) |
| ESP-IDF、组件、图标和语音模型 | 各自许可；以锁定版本和实际构建依赖为准 | `dependencies.lock`、`main/idf_component.yml` 及下载组件内的 LICENSE / NOTICE |
| 厂商硬件资源链接 | 原厂 / 商家内容；本公开快照未收录原始厂商文件或照片，不由本项目重新授予 MIT 许可 | [硬件资料来源](doc/hardware/README.md) |

字体生成物仍是字体衍生物；分发固件时应保留字体许可证。组件使用的 Material Symbols 等图标也应保留其来源与许可，不能仅凭组件外层许可推定所有字形许可。

## 下载依赖与固件分发

`managed_components/`、`components/` 和工具链没有纳入 Git；源码依赖锁文件不等于固件许可清单。

当前锁定依赖中，ESP-SR 及部分音频库带 Espressif 使用范围限制，不能统称为无限制 MIT：

- [ESP-SR 对应版本许可](https://github.com/espressif/esp-sr/blob/2f8c4b0459db5bbb39abd77adae27962d6d94bcb/LICENSE)。
- [esp_audio_codec 对应版本许可](https://github.com/espressif/esp-adf-libs/blob/3bb83597d07b604e1ab5b78dd4370a28d6fa802d/esp_audio_codec/LICENSE)。
- [esp_audio_effects 对应版本许可](https://github.com/espressif/esp-adf-libs/blob/89aa3c399c60045880854ffbd314258b49c671e1/esp_audio_effects/LICENSE)。

公开固件前，按实际解析的版本收集 LICENSE / NOTICE、字体和模型说明，并确认目标与分发方式符合其条款。本文件是来源索引，不代替这些许可全文。

## 厂商资料与照片

`doc/hardware/README.md` 只提供官方资源链接。本公开快照未收录原厂 PDF、STEP、尺寸图、商家照片或包含这些资料的历史归档；这些外部资料不由项目重新授予 MIT 许可。
