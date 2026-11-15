package com.company.bj.voice.cloud.memory.companion;

import java.util.List;

/**
 * 画像驱动的输出守卫。
 *
 * <p>把画像从"一份数据"变成"实际影响输出"：机器人在生成回复前先过这道守卫，
 * 命中忌讳就直接改写为安全话术，而不是生成后再检查（那时已经说出口了）。
 *
 * <p><b>拦截时机在生成之前</b>：输出审核若放在生成之后，
 * 已经生成的违规内容虽然被拦下，但模型算力已经花掉，
 * 而且"重生成"往往还是违规的 —— 因为约束没进生成过程。
 */
public class ProfileResponseGuard {

    /** 画像存储。 */
    private final UserProfileStore profileStore;

    /** 安全话术提供方。 */
    private final SafePhraseProvider safePhrases;

    /** 忌讳匹配器。 */
    private final TabooMatcher tabooMatcher;

    /**
     * 构造画像守卫。
     *
     * @param profileStore 画像存储
     * @param safePhrases  安全话术提供方
     */
    public ProfileResponseGuard(UserProfileStore profileStore, SafePhraseProvider safePhrases) {
        this(profileStore, safePhrases, new TabooMatcher());
    }

    /**
     * 构造画像守卫。
     *
     * @param profileStore  画像存储
     * @param safePhrases   安全话术提供方
     * @param tabooMatcher 忌讳匹配器
     */
    public ProfileResponseGuard(
        UserProfileStore profileStore, SafePhraseProvider safePhrases, TabooMatcher tabooMatcher) {
        this.profileStore = profileStore;
        this.safePhrases = safePhrases;
        this.tabooMatcher = tabooMatcher;
    }

    /**
     * 校验并按需改写回复。
     *
     * @param scopeKey 作用域键
     * @param reply    待下发的回复
     * @return 守卫结果
     */
    public GuardResult guard(String scopeKey, String reply) {
        UserProfile profile = profileStore.load(scopeKey);

        List<String> hits = tabooMatcher.matchedTaboos(reply, profile.taboos());

        if (hits.isEmpty()) {
            return new GuardResult(reply, false, List.of(), profile);
        }

        // 命中忌讳时给出的是**不重复忌讳字样**的兜底话术 ——
        // 直接说"我不能提这个话题"反而把忌讳词又说了一遍。
        return new GuardResult(safePhrases.tabooRedirect(profile), true, hits, profile);
    }

    /**
     * 画像守卫的结果。
     *
     * @param reply        实际可下发的回复
     * @param intercepted  是否发生了拦截
     * @param hits         命中的忌讳话题
     * @param profile      生效的画像
     */
    public record GuardResult(
        String reply, boolean intercepted, List<String> hits, UserProfile profile) {
    }

    /**
     * 安全话术提供方。
     *
     * <p>抽成接口是为了让守卫不依赖具体的文案来源 ——
     * 生产用固定话术表，评测可替换为可控的替身。
     */
    @FunctionalInterface
    public interface SafePhraseProvider {

        /**
         * 给出命中忌讳时的替代话术。
         *
         * @param profile 生效的画像
         * @return 替代话术
         */
        String tabooRedirect(UserProfile profile);
    }
}
