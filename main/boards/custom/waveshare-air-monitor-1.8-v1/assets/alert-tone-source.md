# AIR 浓度告警短提示音

这是本项目自行合成的声音，未使用下载音效、音乐或语音素材。生成源码在 `scripts/generate_air_alert_tone.py`，可按本仓库许可证使用。

- 16 kHz、单声道，原始波形长 240 ms。
- 740 Hz 与 1108 Hz 正弦叠加，权重为 0.72 / 0.28；整体幅度系数 0.18。
- 起音淡入 8 ms，指数衰减时间常数 90 ms，末尾淡出 20 ms。
- 原始 PCM 的 RMS 为 -27.96 dBFS，峰值为满量程的 0.1569。
- 编码为 16 kbit/s CBR、60 ms 帧长的 Opus，Ogg 文件共 760 字节。
- 解码队列接收 5 个 60 ms 包，总时长 300 ms；包含 Opus 起始延迟与末尾填充。播放器沿用现有短音路径，不自行裁剪 Ogg granule，因此不把原始 240 ms 当作最终扬声器占用时间。

生成命令（此次使用 ffmpeg 8.1 / libopus）：

```sh
python3 scripts/generate_air_alert_tone.py --ffmpeg /opt/homebrew/bin/ffmpeg
```

脚本直接生成 `air_alert_tone.h`，固件使用该头文件中的只读字节，不依赖运行时资源文件。添加 `--preview /tmp/air-alert.ogg` 可生成本地试听文件。Ogg 随机序列号被固定并重新计算逐页 CRC；相同编码器下重复生成结果一致。生成头含 Ogg SHA256 供复核；不同 libopus 版本可能产生不同的编码字节，修改后需重新运行针对性测试。

`TryPlayAirAlertTone` 只应由 application 任务调用。调用者检查告警轮次、用户启用的声音设置、当前输出音量大于 0、设备空闲、未关机，并消耗本轮提示音机会；helper 本身再次检查播放队列空闲。已有声音播放、队列已满或投递失败时直接跳过，不延迟重放，不重置解码器，不修改音量，不等待队列腾空。播放任务按原有流程唤起功放。

测试：

```sh
python3 -m unittest scripts.tests.test_air_alert_sound -v
```

测试使用真实 OggDemuxer 和固件内的声音字节；仅替换硬件音频队列。检查单声道、采样率、帧长、时长、原始 payload、忙碌时跳过、满队列不等待、投递失败立即停止，以及不调用 PlaySound / ResetDecoder / 音量与功放控制接口。实际听感和不同音量下的扬声器表现仍需设备验证。
