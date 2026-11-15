package com.company.bj.voice.cloud.agent;

import com.company.bj.voice.cloud.memory.companion.UserProfile;
import com.company.bj.voice.cloud.memory.companion.UserProfileStore;
import java.util.List;
import java.util.Set;

/**
 * 画像更新子智能体。
 *
 * <p>负责从用户话语里抽取<b>画像增量</b>（称呼、语气偏好、忌讳、情绪基线），
 * 并以增量方式更新画像。
 *
 * <p>同样是<b>副作用型</b>处理器：不产生用户可见回复，优先级最低。
 */
public class ProfileUpdateSubAgent implements SubAgentHandler {

    /** 画像更新子智能体的优先级。最低。 */
    public static final int PRIORITY = SubAgentArbitrator.PRIORITY_EMOTION + 10;

    /** 画像更新类意图。 */
    public static final String INTENT_PROFILE_UPDATE = "profile_update";

    /** 画像存储。 */
    private final UserProfileStore profileStore;

    /** 称呼抽取器。 */
    private final AddressExtractor addressExtractor;

    /** 忌讳抽取器。 */
    private final TabooExtractor tabooExtractor;

    /**
     * 构造画像更新子智能体。
     *
     * @param profileStore     画像存储
     * @param addressExtractor 称呼抽取器
     * @param tabooExtractor   忌讳抽取器
     */
    public ProfileUpdateSubAgent(
        UserProfileStore profileStore,
        AddressExtractor addressExtractor,
        TabooExtractor tabooExtractor) {
        this.profileStore = profileStore;
        this.addressExtractor = addressExtractor;
        this.tabooExtractor = tabooExtractor;
    }

    @Override
    public SubAgentResult handle(SubAgentRequest request) {
        String address = addressExtractor.extract(request.text());
        Set<String> taboos = tabooExtractor.extract(request.text());

        UserProfileStore.ProfileDelta delta =
            new UserProfileStore.ProfileDelta(
                address, null, java.util.Map.of(), taboos, null);

        profileStore.apply(profileStore.currentScopeKey(), delta);
        return SubAgentResult.of("", request.intent(), "neutral");
    }

    @Override
    public List<String> supportedIntents() {
        return List.of(INTENT_PROFILE_UPDATE);
    }

    @Override
    public int priority() {
        return PRIORITY;
    }

    /**
     * 称呼抽取器。
     *
     * <p>抽成接口：称呼的识别方式（正则/模型/规则表）会演进，
     * 但子智能体的编排逻辑不该跟着变。
     */
    @FunctionalInterface
    public interface AddressExtractor {

        /**
         * 从文本中抽取用户希望被称呼的名字。
         *
         * @param text 用户文本
         * @return 称呼；未识别到时返回空字符串
         */
        String extract(String text);
    }

    /**
     * 忌讳抽取器。
     */
    @FunctionalInterface
    public interface TabooExtractor {

        /**
         * 从文本中抽取用户声明的忌讳话题。
         *
         * @param text 用户文本
         * @return 忌讳话题集合；未识别到时返回空集合
         */
        Set<String> extract(String text);
    }
}
