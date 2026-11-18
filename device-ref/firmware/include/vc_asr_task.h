/**
 * @file vc_asr_task.h
 * @brief 端侧 ASR 任务接口。
 *
 * 任务职责：接收 VAD 切出的一段语音 → 调用识别后端 → 产出文本与置信度。
 *
 * 识别后端由厂商 SDK 或量化小模型提供（见 device-ref/README.md 的"未验证项"），
 * 本接口只定义**调用方契约**，不绑定具体实现。
 *
 * 置信度必须如实上报：意图判定依赖置信度做降级，
 * 把"不确定"报成"确定"会让端侧在识别错误时自信地走错分支。
 */

#ifndef VC_ASR_TASK_H
#define VC_ASR_TASK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "vc_audio_task.h"

/** 识别文本最大长度（字节）。 */
#define VC_ASR_TEXT_MAX 256

/** 置信度分母。与 vc_protocol.h 的 VC_CONFIDENCE_SCALE 一致。 */
#define VC_ASR_CONFIDENCE_SCALE 1000

/**
 * 一段识别结果。
 */
typedef struct {
    /** 识别文本，以 '\0' 结尾。 */
    char text[VC_ASR_TEXT_MAX];

    /** 置信度，取值 0~VC_ASR_CONFIDENCE_SCALE。 */
    uint16_t confidence;

    /** 识别耗时（毫秒）。用于端侧指标采集。 */
    uint32_t latency_ms;
} vc_asr_result_t;

/**
 * 识别完成回调。
 *
 * @param result 识别结果
 * @param user_data 调用方上下文
 */
typedef void (*vc_asr_result_cb_t)(const vc_asr_result_t *result, void *user_data);

/**
 * 初始化识别任务。
 *
 * @param result_cb 识别完成回调
 * @param user_data 回调上下文
 * @return true 表示初始化成功
 */
bool vc_asr_task_init(vc_asr_result_cb_t result_cb, void *user_data);

/**
 * 启动识别任务。
 *
 * @return true 表示启动成功
 */
bool vc_asr_task_start(void);

/**
 * 停止识别任务。
 *
 * @return true 表示停止成功
 */
bool vc_asr_task_stop(void);

/**
 * 提交一段待识别的语音。
 *
 * @param frames 语音帧序列
 * @param frame_count 帧数
 * @return true 表示提交成功
 */
bool vc_asr_task_submit(
    const vc_audio_frame_t *frames, size_t frame_count);

/**
 * 读取最后一次识别结果。
 *
 * @param out_result 接收缓冲
 * @return true 表示有可读结果
 */
bool vc_asr_task_last_result(vc_asr_result_t *out_result);

#endif /* VC_ASR_TASK_H */
