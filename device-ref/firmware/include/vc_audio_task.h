/**
 * @file vc_audio_task.h
 * @brief 音频采集与 VAD 任务接口。
 *
 * 任务职责：I2S/DMA 采集 → 帧组装 → VAD 判定 → 输出 20ms 一帧的 PCM。
 *
 * 为什么帧长必须固定：上行协议按固定帧长切分（见 vc_protocol.h），
 * 变长帧会让云端的分片重组与端侧的帧序号对不上 ——
 * 表现为"偶发丢字"，且只在语音长短不一时出现，极难定位。
 *
 * 音频常量必须与端侧协商默认值一致
 * （core.edge.audio.negotiation.DEFAULT_FORMAT），
 * 由 core/tests/device_ref/test_firmware_interfaces.py 守住。
 */

#ifndef VC_AUDIO_TASK_H
#define VC_AUDIO_TASK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** 采样率（Hz）。16kHz 窄带，端侧 ASR 与云端嵌入模型的共同规格。 */
#define VC_AUDIO_SAMPLE_RATE_HZ 16000

/** 声道数。协议当前只支持单声道。 */
#define VC_AUDIO_CHANNELS 1

/** 每采样点位数。 */
#define VC_AUDIO_BITS_PER_SAMPLE 16

/** 单帧时长（毫秒）。20ms 是实时语音的常规取帧间隔。 */
#define VC_AUDIO_FRAME_DURATION_MS 20

/** 单帧采样点数。必须与采样率、帧长自洽，否则时间戳会漂移。 */
#define VC_AUDIO_FRAME_SAMPLES 320

/** 单帧字节数。16bit 单声道下为采样点数 × 2。 */
#define VC_AUDIO_FRAME_BYTES 640

/** VAD 语音概率阈值。低于此值不认为是语音。 */
#define VC_VAD_SPEECH_PROBABILITY_THRESHOLD 600

/** VAD 能量阈值（RMS，千分比）。低于此值不认为是语音。 */
#define VC_VAD_RMS_THRESHOLD 10

/** 断句尾静音阈值（毫秒）。 */
#define VC_AUDIO_SEGMENT_END_SILENCE_MS 600

/** 说话轮次切换静音阈值（毫秒）。 */
#define VC_AUDIO_TURN_CHANGE_SILENCE_MS 2000

/**
 * 一帧音频。
 *
 * 用定长数组而不是指针：帧在任务间传递，栈上分配的生命周期比堆可控，
 * 且避免"消费方还没用完，采集方就把它回收了"这类竞态。
 */
typedef struct {
    /** PCM 负载，长度不超过 VC_AUDIO_FRAME_BYTES。 */
    int16_t samples[VC_AUDIO_FRAME_SAMPLES];

    /** 实际采样点数。末帧补齐时小于 VC_AUDIO_FRAME_SAMPLES。 */
    uint16_t sample_count;

    /** 帧起始时间戳（毫秒）。 */
    uint32_t timestamp_ms;

    /** 是否为补齐的末帧。 */
    bool is_final_partial;
} vc_audio_frame_t;

/**
 * 音频采集任务的事件回调。
 *
 * @param frame 采集到的一帧
 * @param user_data 调用方上下文
 */
typedef void (*vc_audio_frame_cb_t)(const vc_audio_frame_t *frame, void *user_data);

/**
 * 初始化音频采集任务。
 *
 * @param frame_cb 帧就绪回调
 * @param user_data 回调上下文
 * @return true 表示初始化成功
 */
bool vc_audio_task_init(vc_audio_frame_cb_t frame_cb, void *user_data);

/**
 * 启动音频采集任务。
 *
 * @return true 表示启动成功
 */
bool vc_audio_task_start(void);

/**
 * 停止音频采集任务。
 *
 * 停止后 VAD 状态与断句缓冲会被清空 —— 保留上一轮的尾巴会让
 * 下一轮的第一帧被判成"紧接上一句"，把两句话连成一句。
 *
 * @return true 表示停止成功
 */
bool vc_audio_task_stop(void);

/**
 * 读取当前 VAD 判定结果。
 *
 * @return true 表示当前处于语音段
 */
bool vc_audio_task_in_speech(void);

/**
 * 取出一段完整的语音帧序列。
 *
 * @param out_frames 接收缓冲
 * @param max_frames 缓冲能容纳的帧数
 * @param out_count 实际取出的帧数
 * @return true 表示取到了一段（断句结束）
 */
bool vc_audio_task_take_segment(
    vc_audio_frame_t *out_frames, size_t max_frames, size_t *out_count);

#endif /* VC_AUDIO_TASK_H */
