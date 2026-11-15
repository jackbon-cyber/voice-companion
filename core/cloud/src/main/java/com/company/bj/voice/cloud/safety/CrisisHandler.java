package com.company.bj.voice.cloud.safety;

/**
 * 危机干预处理器。
 *
 * <p>识别到危机信号后，本轮<b>不进入常规陪伴流程</b> ——
 * 不做共情、不做记忆写入、不做意图执行，只做一件事：
 * 转安全话术并给出求助渠道。
 *
 * <p><b>为什么危机轮要完全绕过常规流程</b>：
 * 常规流程里的共情话术（"我懂你的难过"）在危机语境下是
 * <b>不恰当</b>的 —— 用户表达的是想死，而机器人回"我懂你的难过"，
 * 等于把一句轻飘飘的共情放在最重的时刻。
 * 危机轮需要的是<b>明确的求助指引</b>，不是情绪回应。
 *
 * <p><b>求助渠道必须具体</b>：给一句"你要加油"或"想想 positives"是
 * 有害的 —— 那是在用户最需要帮助时否定了求助的必要性。
 * 因此本处理器要求渠道提示<b>非空且包含可拨打的号码</b>。
 */
public class CrisisHandler {

    /** 求助渠道提示。 */
    private final String guidance;

    /** 危机场景下的回复模板。 */
    private final String template;

    /**
     * 构造危机处理器。
     *
     * @param guidance 求助渠道提示；必须包含可拨打的号码
     * @param template 危机场景下的回复模板；{@code {guidance}} 会被替换为渠道提示
     */
    public CrisisHandler(String guidance, String template) {
        if (guidance == null || guidance.isBlank()) {
            throw new IllegalArgumentException(
                "crisis guidance must be provided: an empty channel gives the user no way out");
        }
        if (!guidance.matches(".*\\d{3,}.*")) {
            throw new IllegalArgumentException(
                "crisis guidance must contain a dialable number");
        }
        this.guidance = guidance;
        this.template = template;
    }

    /**
     * 生成危机场景下的回复。
     *
     * @param review 审核结论
     * @return 危机回复
     */
    public String respond(SafetyReviewer.Review review) {
        String reply = template.replace("{guidance}", guidance);
        return reply + " " + guidance;
    }

    /**
     * 判断该审核结论是否需要危机干预。
     *
     * @param review 审核结论
     * @return 需要危机干预返回 {@code true}
     */
    public boolean shouldIntercept(SafetyReviewer.Review review) {
        return review != null && review.crisis();
    }

    /**
     * 返回求助渠道提示。
     *
     * @return 渠道提示
     */
    public String guidance() {
        return guidance;
    }
}
