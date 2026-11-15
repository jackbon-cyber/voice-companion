package com.company.bj.voice.cloud.memory.companion;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 用户画像存储与增量下发。
 *
 * <p>画像随对话逐步累积：机器人每轮从用户话语里抽到新的偏好，
 * 就以<b>增量</b>的方式更新画像，而不是每轮重算全量。
 *
 * <p><b>为什么是增量</b>：全量重算需要重扫全部历史，
 * 随会话变长成本线性上升，且会丢掉"用户曾经明确说过、后来没说"的信息 ——
 * 而那恰恰是最有价值的长期信号。
 *
 * <p><b>忌讳是单向累积的</b>：用户一旦说"别提前任"，这条忌讳就<b>永久生效</b>，
 * 不会因为后续几轮没再提起而消失。
 */
public class UserProfileStore {

    /** 话题权重的初始值。 */
    public static final double INITIAL_TOPIC_WEIGHT = 0.5;

    /** 话题权重的最大值。 */
    public static final double MAX_TOPIC_WEIGHT = 1.0;

    /** 话题权重的增量。 */
    public static final double TOPIC_WEIGHT_STEP = 0.1;

    /** 各作用域的画像。 */
    private final Map<String, UserProfile> profiles = new LinkedHashMap<>();

    /** 当前作用域键。 */
    private volatile String currentScopeKey = DEFAULT_SCOPE_KEY;

    /** 默认作用域键。 */
    public static final String DEFAULT_SCOPE_KEY = "default-user";

    /**
     * 设置当前作用域键。
     *
     * <p>画像的读写方很多（画像更新子智能体、上下文装配器、守卫），
     * 让它们各自传作用域键容易出错 —— 传错就会写到别人的画像上。
     * 改为由入口处设置一次当前作用域。
     *
     * @param scopeKey 作用域键
     */
    public void useScope(String scopeKey) {
        this.currentScopeKey = scopeKey == null || scopeKey.isBlank() ? DEFAULT_SCOPE_KEY : scopeKey;
    }

    /**
     * 返回当前作用域键。
     *
     * @return 作用域键
     */
    public String currentScopeKey() {
        return currentScopeKey;
    }

    /**
     * 读取画像。
     *
     * @param scopeKey 作用域键
     * @return 画像；不存在时返回空画像
     */
    public UserProfile load(String scopeKey) {
        return profiles.getOrDefault(scopeKey, UserProfile.empty());
    }

    /**
     * 应用一份画像增量。
     *
     * @param scopeKey 作用域键
     * @param delta    增量内容
     * @return 更新后的完整画像
     */
    public UserProfile apply(String scopeKey, ProfileDelta delta) {
        UserProfile current = load(scopeKey);

        String address = delta.preferredAddress() == null || delta.preferredAddress().isBlank()
            ? current.preferredAddress()
            : delta.preferredAddress();

        UserProfile.Tone tone = delta.tone() == null ? current.tone() : delta.tone();

        UserProfile.EmotionalBaseline baseline = delta.emotionalBaseline() == null
            ? current.emotionalBaseline()
            : delta.emotionalBaseline();

        Map<String, Double> topics = new LinkedHashMap<>(current.topicWeights());
        for (Map.Entry<String, Double> entry : delta.topicWeights().entrySet()) {
            double currentWeight = topics.getOrDefault(entry.getKey(), INITIAL_TOPIC_WEIGHT);
            topics.put(entry.getKey(),
                Math.min(MAX_TOPIC_WEIGHT, currentWeight + entry.getValue()));
        }

        // 忌讳单向累积：只增不减。
        Set<String> taboos = new LinkedHashSet<>(current.taboos());
        taboos.addAll(delta.taboos());

        UserProfile updated = UserProfile.of(address, tone, topics, taboos, baseline);
        profiles.put(scopeKey, updated);
        return updated;
    }

    /**
     * 判断话题是否应被拦截。
     *
     * @param scopeKey 作用域键
     * @param topic    话题文本
     * @return 应拦截返回 {@code true}
     */
    public boolean blocked(String scopeKey, String topic) {
        return load(scopeKey).isTaboo(topic);
    }

    /**
     * 列出某作用域的全部忌讳。
     *
     * @param scopeKey 作用域键
     * @return 忌讳话题集合
     */
    public Set<String> taboosOf(String scopeKey) {
        return load(scopeKey).taboos();
    }

    /**
     * 清空某作用域的画像。
     *
     * @param scopeKey 作用域键
     */
    public void clear(String scopeKey) {
        profiles.remove(scopeKey);
    }

    /**
     * 画像增量。
     *
     * @param preferredAddress  称呼；为空表示不变
     * @param tone              语气；为空表示不变
     * @param topicWeights      话题权重增量
     * @param taboos            新增忌讳
     * @param emotionalBaseline 情绪基线；为空表示不变
     */
    public record ProfileDelta(
        String preferredAddress,
        UserProfile.Tone tone,
        Map<String, Double> topicWeights,
        Set<String> taboos,
        UserProfile.EmotionalBaseline emotionalBaseline) {

        /**
         * 构造一个空增量。
         *
         * @return 空增量
         */
        public static ProfileDelta empty() {
            return new ProfileDelta(null, null, Map.of(), Set.of(), null);
        }

        /**
         * 构造一个只带称呼的增量。
         *
         * @param preferredAddress 称呼
         * @return 增量
         */
        public static ProfileDelta address(String preferredAddress) {
            return new ProfileDelta(preferredAddress, null, Map.of(), Set.of(), null);
        }

        /**
         * 构造一个只带新增忌讳的增量。
         *
         * @param taboos 忌讳话题
         * @return 增量
         */
        public static ProfileDelta taboos(Set<String> taboos) {
            return new ProfileDelta(null, null, Map.of(), taboos, null);
        }

        /**
         * 构造一个只带话题权重增量的增量。
         *
         * @param topicWeights 话题权重增量
         * @return 增量
         */
        public static ProfileDelta topics(Map<String, Double> topicWeights) {
            return new ProfileDelta(null, null, topicWeights, Set.of(), null);
        }
    }
}
