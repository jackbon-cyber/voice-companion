package com.company.bj.voice.cloud.memory.companion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link UserProfileStore} 与 {@link ProfileResponseGuard} 的行为测试。
 *
 * <p>核心断言：<b>画像实际影响输出</b>且<b>忌讳话题被拦截</b>。
 */
class UserProfileStoreTest {

    /** 作用域键。 */
    private static final String SCOPE = "default-user";

    /** 被测存储。 */
    private final UserProfileStore store = new UserProfileStore();

    @Test
    @DisplayName("空作用域返回空画像")
    void 空作用域返回空画像() {
        UserProfile profile = store.load("未存在的作用域");

        assertTrue(profile.blank());
        assertEquals("", profile.preferredAddress());
        assertTrue(profile.taboos().isEmpty());
    }

    @Test
    @DisplayName("称呼增量生效")
    void 称呼增量生效() {
        UserProfile profile = store.apply(SCOPE, UserProfileStore.ProfileDelta.address("小张"));

        assertEquals("小张", profile.preferredAddress());
        assertEquals("小张", store.load(SCOPE).preferredAddress());
    }

    @Test
    @DisplayName("话题权重随增量累积")
    void 话题权重随增量累积() {
        store.apply(SCOPE, UserProfileStore.ProfileDelta.topics(Map.of("工作", 0.1)));
        UserProfile profile = store.apply(SCOPE,
            UserProfileStore.ProfileDelta.topics(Map.of("工作", 0.1)));

        assertTrue(profile.topicWeight("工作") > 0.5,
            "话题权重应累积，实际 " + profile.topicWeight("工作"));
    }

    @Test
    @DisplayName("忌讳单向累积不消失")
    void 忌讳单向累积不消失() {
        store.apply(SCOPE, UserProfileStore.ProfileDelta.taboos(Set.of("前任")));
        store.apply(SCOPE, UserProfileStore.ProfileDelta.address("小张"));

        assertTrue(store.load(SCOPE).isTaboo("前任"),
            "后续增量不应让既有忌讳消失");
    }

    @Test
    @DisplayName("忌讳可被换一种说法绕过——因此按子串匹配拦截")
    void 忌讳可被换一种说法绕过因此按子串匹配拦截() {
        store.apply(SCOPE, UserProfileStore.ProfileDelta.taboos(Set.of("前任")));

        assertTrue(store.blocked(SCOPE, "我前男友"), "换个说法也应被拦截");
        assertTrue(store.blocked(SCOPE, "前任的事"));
        assertFalse(store.blocked(SCOPE, "今天天气不错"));
    }

    @Test
    @DisplayName("画像实际影响输出：命中忌讳时回复被改写")
    void 画像实际影响输出命中忌讳时回复被改写() {
        store.apply(SCOPE, UserProfileStore.ProfileDelta.taboos(Set.of("前任")));
        ProfileResponseGuard guard = new ProfileResponseGuard(store,
            profile -> "我们说点别的吧。");

        ProfileResponseGuard.GuardResult result = guard.guard(SCOPE, "你前任最近怎么样？");

        assertTrue(result.intercepted());
        assertEquals("我们说点别的吧。", result.reply());
        assertEquals(Set.of("前任"), Set.copyOf(result.hits()));
    }

    @Test
    @DisplayName("未命中忌讳时回复原样通过")
    void 未命中忌讳时回复原样通过() {
        store.apply(SCOPE, UserProfileStore.ProfileDelta.taboos(Set.of("前任")));
        ProfileResponseGuard guard = new ProfileResponseGuard(store,
            profile -> "我们说点别的吧。");

        ProfileResponseGuard.GuardResult result = guard.guard(SCOPE, "今天过得怎么样？");

        assertFalse(result.intercepted());
        assertEquals("今天过得怎么样？", result.reply());
    }

    @Test
    @DisplayName("拦截话术本身不含忌讳字样")
    void 拦截话术本身不含忌讳字样() {
        store.apply(SCOPE, UserProfileStore.ProfileDelta.taboos(Set.of("前任")));
        // 兜底话术若复述忌讳词，就把忌讳又说了一遍 —— 那是二次伤害。
        ProfileResponseGuard guard = new ProfileResponseGuard(store,
            profile -> "我们说点别的吧。");

        ProfileResponseGuard.GuardResult result = guard.guard(SCOPE, "聊聊你前任吧");

        assertFalse(result.reply().contains("前任"),
            "拦截话术不应复述忌讳字样：" + result.reply());
    }

    @Test
    @DisplayName("清空后画像回到空状态")
    void 清空后画像回到空状态() {
        store.apply(SCOPE, UserProfileStore.ProfileDelta.address("小张"));
        store.clear(SCOPE);

        assertTrue(store.load(SCOPE).blank());
    }
}
