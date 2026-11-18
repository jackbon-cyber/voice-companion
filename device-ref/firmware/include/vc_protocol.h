/**
 * @file vc_protocol.h
 * @brief 端云协议字段名常量与消息类型定义。
 *
 * 设备侧不解析 JSON —— flash 占用与实时性都不允许引入 JSON 解析器。
 * 但**字段名必须与 core/protocol/schema/ 保持一致**，否则：
 *   - schema 新增字段时，固件侧无人察觉，表现为"新特性在真机上不生效"；
 *   - 字段拼错时，编译通过、联调才发现，是最贵的失败形态。
 *
 * 因此本文件把每个字段名固化成常量（值为 schema 里的原始字段名），
 * 由 core/tests/device_ref/test_firmware_interfaces.py 守着这份对应关系：
 * schema 改了字段名而固件没改，测试立刻失败。
 *
 * 协议演进需两侧同步。
 */

#ifndef VC_PROTOCOL_H
#define VC_PROTOCOL_H

#include <stdbool.h>
#include <stdint.h>

/** 协议消息类型。取值与 schema 文件名一一对应。 */
typedef enum {
    VC_MSG_AUDIO_FRAME = 0,       /**< audio-frame：上行音频帧 */
    VC_MSG_VOICE_CHUNK = 1,       /**< voice-chunk：下行语音分片 */
    VC_MSG_TEXT_REPLY = 2,        /**< text-reply：下行文本回复 */
    VC_MSG_SESSION = 3,           /**< session：会话生命周期 */
    VC_MSG_AUDIO_NEGOTIATION = 4, /**< audio-negotiation：音频格式协商 */
    VC_MSG_DEGRADE_LEVEL = 5,     /**< degrade-level：降级档位变更 */
    VC_MSG_CONTROL_CHANNEL = 6,   /**< control-channel：控制通道 */
    VC_MSG_INTENT_REPORT = 7      /**< intent-report：端侧意图上报 */
} vc_message_type_t;

/**
 * 协议处理结果。
 *
 * 为什么显式拒绝而不是静默忽略：静默忽略会让"新协议在旧固件上不生效"
 * 这件事完全不可见 —— 用户只看到"设备不响应了"。
 * 拒绝会让旧固件在收到新消息时明确回一个错误码。
 */
typedef enum {
    VC_PROTOCOL_OK = 0,       /**< 消息可处理 */
    VC_PROTOCOL_UNKNOWN = -1, /**< 未知消息类型，必须拒绝 */
    VC_PROTOCOL_INVALID = -2  /**< 已知类型但字段非法 */
} vc_protocol_result_t;

/* ------------------------------------------------------------------ */
/* 协议字段名常量                                                      */
/*                                                                      */
/* 值为 schema 中的原始字段名。固件按名字拼装载荷，避免手写字符串。   */
/* ------------------------------------------------------------------ */

/** 会话标识。 */
#define VC_SESSION_ID "sessionId"

/** 消息序号。 */
#define VC_SEQUENCE "sequence"

/** 时间戳（毫秒）。 */
#define VC_TIMESTAMP_MS "timestampMs"

/** 音频帧负载（Base64）。 */
#define VC_PAYLOAD_BASE64 "payloadBase64"

/** 文本内容。 */
#define VC_TEXT "text"

/** 首片标志。 */
#define VC_IS_FIRST "isFirst"

/** 末片标志。 */
#define VC_IS_LAST "isLast"

/** 意图标识。 */
#define VC_INTENT "intent"

/** 意图置信度。 */
#define VC_CONFIDENCE "confidence"

/** 控制通道方向。 */
#define VC_DIRECTION "direction"

/** 通用类型字段（session 的 type / control-channel 的 type）。 */
#define VC_TYPE "type"

/** 降级档位。 */
#define VC_LEVEL "level"

/** 降级原因。 */
#define VC_REASON "reason"

/* ------------------------------------------------------------------ */
/* 容量与量纲                                                          */
/* ------------------------------------------------------------------ */

/** 会话标识缓冲区长度。 */
#define VC_SESSION_ID_MAX 64

/** 帧负载的 Base64 编码长度上限（编码后字符数）。 */
#define VC_PAYLOAD_BASE64_MAX 2048

/** 回复文本最大长度（字节）。 */
#define VC_TEXT_MAX 512

/** 意图标识最大长度（字节）。 */
#define VC_INTENT_MAX 64

/** 降级原因最大长度（字节）。 */
#define VC_DEGRADE_REASON_MAX 128

/** 置信度分母。协议用 0.0~1.0 浮点，固件用千分比整数避免浮点运算。 */
#define VC_CONFIDENCE_SCALE 1000

/** 帧补齐标志：末帧不足整帧时补齐并置位。 */
#define VC_IS_FINAL_PARTIAL true

/* ------------------------------------------------------------------ */
/* 枚举取值                                                            */
/* ------------------------------------------------------------------ */

/** 会话消息类型：开始。 */
#define VC_SESSION_TYPE_BEGIN "begin"

/** 会话消息类型：结束。 */
#define VC_SESSION_TYPE_END "end"

/** 控制通道方向：上行。 */
#define VC_DIRECTION_UP "up"

/** 控制通道方向：下行。 */
#define VC_DIRECTION_DOWN "down"

/** 控制通道载荷类型：人设增量下发。 */
#define VC_CONTROL_TYPE_PROFILE_DELTA "profile_delta"

/** 降级档位：正常。 */
#define VC_DEGRADE_LEVEL_NORMAL "NORMAL"

/** 降级档位：网络降级。 */
#define VC_DEGRADE_LEVEL_DEGRADED_NETWORK "DEGRADED_NETWORK"

/** 降级档位：离线。 */
#define VC_DEGRADE_LEVEL_OFFLINE "OFFLINE"

/** 降级档位：最小功能。 */
#define VC_DEGRADE_LEVEL_MINIMAL "MINIMAL"

/**
 * 判断一条消息类型是否受支持。
 *
 * @param type 消息类型
 * @return true 表示已知类型
 */
bool vc_protocol_is_known_type(vc_message_type_t type);

#endif /* VC_PROTOCOL_H */
