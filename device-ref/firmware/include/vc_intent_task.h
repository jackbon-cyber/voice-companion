/**
 * @file vc_intent_task.h
 * @brief 端侧意图判定任务接口。
 *
 * 任务职责：接收识别文本 → 判定意图 → 决定本地处理还是上云。
 *
 * 设备侧只做**规则表**判定，不跑模型：模型在 flash 里不划算
 * （体积与算力都不足），且意图判定的容错度低于识别 ——
 * 判错意图会让机器人做出完全不相干的回应。
 *
 * 分流原则：本地能确定的意图（音量、时间、停止说话等固定指令）在端侧执行，
 * 其余上云。端侧执行的前提是**可逆且低风险** ——
 * 不可逆的操作（支付、删除）不得放在端侧。
 */

#ifndef VC_INTENT_TASK_H
#define VC_INTENT_TASK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** 意图标识最大长度（字节）。 */
#define VC_INTENT_NAME_MAX 64

/** 置信度分母。 */
#define VC_INTENT_CONFIDENCE_SCALE 1000

/**
 * 低于此置信度的判定降级为纯关键词匹配。
 *
 * **必须与 PC 侧一致**：`core.edge.intent.detector.RECOGNITION_CONFIDENCE_THRESHOLD`
 * 是 0.5，即千分比 500。两侧不一致时，同一句话在固件上按关键词执行、
 * 在模拟端却拒识 —— 开发者以为的行为与真机不一致。
 * 由 core/tests/device_ref/test_behavior_contract.py 守着。
 */
#define VC_INTENT_KEYWORD_ONLY_THRESHOLD 500

/**
 * 意图判定结果。
 */
typedef struct {
    /** 意图标识。无法判定时为 "unknown"。 */
    char intent[VC_INTENT_NAME_MAX];

    /** 置信度，取值 0~VC_INTENT_CONFIDENCE_SCALE。 */
    uint16_t confidence;

    /** 是否在端侧本地处理。true 表示无需上云。 */
    bool handled_locally;

    /** 是否因置信度不足而降级为关键词匹配。 */
    bool keyword_only;
} vc_intent_result_t;

/**
 * 意图判定回调。
 *
 * @param result 判定结果
 * @param user_data 调用方上下文
 */
typedef void (*vc_intent_result_cb_t)(const vc_intent_result_t *result, void *user_data);

/**
 * 初始化意图判定任务。
 *
 * @param result_cb 判定完成回调
 * @param user_data 回调上下文
 * @return true 表示初始化成功
 */
bool vc_intent_task_init(vc_intent_result_cb_t result_cb, void *user_data);

/**
 * 启动意图判定任务。
 *
 * @return true 表示启动成功
 */
bool vc_intent_task_start(void);

/**
 * 停止意图判定任务。
 *
 * @return true 表示停止成功
 */
bool vc_intent_task_stop(void);

/**
 * 提交一段文本做意图判定。
 *
 * @param text 识别文本
 * @return true 表示提交成功
 */
bool vc_intent_task_submit(const char *text);

/**
 * 读取最近一次意图判定结果。
 *
 * @param out_result 接收缓冲
 * @return true 表示有可读结果
 */
bool vc_intent_task_last_result(vc_intent_result_t *out_result);

#endif /* VC_INTENT_TASK_H */
