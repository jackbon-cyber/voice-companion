/**
 * @file vc_state_machine.h
 * @brief 端侧会话状态机接口。
 *
 * 六态：IDLE / LISTENING / THINKING / WAITING_CLOUD / SPEAKING / INTERRUPTED。
 * 状态集合必须与端侧 Python 实现
 * （core.edge.session.state_machine.SessionState）一致 ——
 * 两端状态集不一致时，固件会停在 Python 侧不存在的状态上，
 * 行为随实现而异，最难复现。
 *
 * 关键语义：
 * - **打断只丢"还没播出去"的音频，不丢"已经识别出的文本"。**
 *   用户打断说"等等"，机器人应把已识别的那句接着说完或道歉，
 *   而不是当作没发生过 —— 这是陪伴场景最不能接受的失败形态。
 * - **超时回到 IDLE**：云端不回或识别器卡住时，卡在 WAITING_CLOUD
 *   意味着麦克风再也不听了 —— 用户说什么都没反应。
 */

#ifndef VC_STATE_MACHINE_H
#define VC_STATE_MACHINE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** 空闲，等待用户开口。 */
#define VC_STATE_IDLE 0

/** 正在接收用户语音。 */
#define VC_STATE_LISTENING 1

/** 端侧处理中（识别、意图判定）。 */
#define VC_STATE_THINKING 2

/** 等待云端下行。 */
#define VC_STATE_WAITING_CLOUD 3

/** 正在播放机器人语音。 */
#define VC_STATE_SPEAKING 4

/** 已被用户打断，正在清理播放缓冲。 */
#define VC_STATE_INTERRUPTED 5

/** 状态总数。 */
#define VC_STATE_TOTAL 6

/** 打断响应延迟上限（毫秒）。超过即视为体验故障。 */
#define VC_INTERRUPT_LATENCY_LIMIT_MS 300

/** 状态超时（毫秒）。超时后强制回到 IDLE。 */
#define VC_DWELL_TIMEOUT_MS 10000

/**
 * 一次状态转移。
 */
typedef struct {
    /** 转移前状态。 */
    int previous;

    /** 转移后状态。 */
    int current;

    /** 触发原因。 */
    const char *reason;

    /** 距上次状态变化的时长（毫秒）。 */
    uint32_t elapsed_ms;
} vc_state_transition_t;

/**
 * 一次打断事件。
 */
typedef struct {
    /** 打断发生时的状态。 */
    int state;

    /** 打断响应延迟（毫秒）。 */
    uint32_t latency_ms;

    /** 被打断时已识别出的文本长度（字节）。 */
    uint16_t retained_text_length;

    /** 被丢弃的待播音频字节数。 */
    uint32_t discarded_audio_bytes;
} vc_barge_in_event_t;

/**
 * 初始化状态机。
 *
 * @return true 表示初始化成功
 */
bool vc_state_machine_init(void);

/**
 * 读取当前状态。
 *
 * @return 当前状态常量
 */
int vc_state_machine_current(void);

/**
 * 处理用户开口。
 *
 * 在机器人说话时即为一次打断。
 *
 * @param now_ms 当前时间戳（毫秒）
 * @param out_event 打断事件；非打断时为 NULL
 * @return true 表示发生了一次打断
 */
bool vc_state_machine_on_user_speech_start(
    uint32_t now_ms, vc_barge_in_event_t *out_event);

/**
 * 记录识别出的文本长度。
 *
 * @param text_length 文本字节数
 */
void vc_state_machine_on_recognized(uint16_t text_length);

/**
 * 机器人开始播放。
 *
 * @param now_ms 当前时间戳（毫秒）
 */
void vc_state_machine_on_playback_started(uint32_t now_ms);

/**
 * 登记待播音频。
 *
 * @param audio_bytes 音频字节数
 */
void vc_state_machine_on_playback_queued(uint32_t audio_bytes);

/**
 * 机器人播完。
 *
 * @param now_ms 当前时间戳（毫秒）
 */
void vc_state_machine_on_playback_finished(uint32_t now_ms);

/**
 * 端侧开始处理。
 *
 * @param now_ms 当前时间戳（毫秒）
 */
void vc_state_machine_on_local_processing_started(uint32_t now_ms);

/**
 * 开始等待云端。
 *
 * @param now_ms 当前时间戳（毫秒）
 */
void vc_state_machine_on_cloud_wait_started(uint32_t now_ms);

/**
 * 检查并处理状态超时。
 *
 * @param now_ms 当前时间戳（毫秒）
 * @param out_transition 超时引发的转移；未超时时为 NULL
 * @return true 表示发生了超时转移
 */
bool vc_state_machine_on_timeout(
    uint32_t now_ms, vc_state_transition_t *out_transition);

#endif /* VC_STATE_MACHINE_H */
