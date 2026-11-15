package com.company.bj.voice.cloud.safety;

/**
 * 云端降级策略。
 *
 * <p>两条降级路径：
 * <ul>
 *   <li><b>TTS 过载</b> —— 语音合成服务不可用时，切换到备用供应商，
 *       再不可用则降为<b>纯文本下发</b>；</li>
 *   <li><b>前端异常</b> —— 客户端渲染失败时，回落到固定话术。</li>
 * </ul>
 *
 * <p><b>降级的终点是"一定有东西发给用户"</b>：
 * 宁可发一句呆板的固定话术，也不要让用户在等待里听到沉默。
 * 沉默在陪伴场景里等于"机器人挂了"，那是比话术不好听得多的体验。
 */
public class CloudDegradePolicy {

    /** 降级档位。 */
    public enum Level {

        /** 正常：使用首选语音供应商。 */
        NORMAL,

        /** 语音过载：切换到备用语音供应商。 */
        BACKUP_VOICE,

        /** 语音不可用：降为纯文本下发。 */
        TEXT_ONLY,

        /** 前端异常：下发固定话术。 */
        FIXED_PHRASE
    }

    /** 首选语音供应商。 */
    private final String primaryVoiceProvider;

    /** 备用语音供应商。 */
    private final String backupVoiceProvider;

    /** 纯文本模式下的兜底话术。 */
    private final String textFallbackPhrase;

    /** 前端异常时的固定话术。 */
    private final String fixedPhrase;

    /** 当前档位。 */
    private volatile Level level = Level.NORMAL;

    /** 首选语音连续失败次数。 */
    private volatile int consecutiveVoiceFailures;

    /** 触发降级的连续失败阈值。 */
    private final int failureThreshold;

    /**
     * 构造降级策略。
     *
     * @param primaryVoiceProvider 首选语音供应商
     * @param backupVoiceProvider  备用语音供应商
     * @param textFallbackPhrase   纯文本模式的兜底话术
     * @param fixedPhrase          前端异常时的固定话术
     * @param failureThreshold     触发降级的连续失败阈值
     */
    public CloudDegradePolicy(
        String primaryVoiceProvider,
        String backupVoiceProvider,
        String textFallbackPhrase,
        String fixedPhrase,
        int failureThreshold) {
        this.primaryVoiceProvider = primaryVoiceProvider;
        this.backupVoiceProvider = backupVoiceProvider;
        this.textFallbackPhrase = textFallbackPhrase;
        this.fixedPhrase = fixedPhrase;
        this.failureThreshold = failureThreshold;
    }

    /**
     * 记录一次语音合成失败。
     *
     * @param provider 失败的供应商
     * @return 降级后的档位
     */
    public Level recordVoiceFailure(String provider) {
        consecutiveVoiceFailures++;
        if (consecutiveVoiceFailures < failureThreshold) {
            return level;
        }
        if (primaryVoiceProvider.equals(provider)) {
            level = Level.BACKUP_VOICE;
        } else {
            // 备用也挂了：降为纯文本，这是最后一道可用形态。
            level = Level.TEXT_ONLY;
        }
        return level;
    }

    /**
     * 记录一次语音合成成功。
     *
     * @return 降级后的档位
     */
    public Level recordVoiceSuccess() {
        consecutiveVoiceFailures = 0;
        if (level == Level.BACKUP_VOICE) {
            // 首选恢复后回到正常档位，但**不直接跳回**：
            // 首选刚刚失败过，立即切回可能又失败。
            // 保守起见保持备用，直到它也成功一次。
            return level;
        }
        level = Level.NORMAL;
        return level;
    }

    /**
     * 记录前端渲染异常。
     *
     * @return 降级后的档位
     */
    public Level recordFrontendFailure() {
        level = Level.FIXED_PHRASE;
        return level;
    }

    /**
     * 返回当前应使用的语音供应商。
     *
     * @return 供应商标识；纯文本与固定话术模式下返回空字符串
     */
    public String currentVoiceProvider() {
        return switch (level) {
            case NORMAL -> primaryVoiceProvider;
            case BACKUP_VOICE -> backupVoiceProvider;
            case TEXT_ONLY, FIXED_PHRASE -> "";
        };
    }

    /**
     * 返回当前档位下应当下发的内容。
     *
     * @param generatedReply 生成的回复
     * @return 实际应下发的内容
     */
    public String contentToDeliver(String generatedReply) {
        return switch (level) {
            case NORMAL, BACKUP_VOICE -> generatedReply;
            case TEXT_ONLY -> textFallbackPhrase;
            case FIXED_PHRASE -> fixedPhrase;
        };
    }

    /**
     * 返回当前降级档位。
     *
     * @return 档位
     */
    public Level level() {
        return level;
    }
}
