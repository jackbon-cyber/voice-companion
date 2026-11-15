package com.company.bj.voice.cloud.agent;

import com.company.bj.voice.cloud.memory.companion.UserProfile;
import java.util.List;

/**
 * 角色扮演子智能体。
 *
 * <p>负责维持陪伴者人设：称呼用户、保持语气一致。
 *
 * <p><b>人设卡是"配置"不是"上下文"</b>：即使上下文预算吃紧，
 * 人设也必须保留 —— 失去人设的机器人会变成一个通用问答机，
 * 那正是陪伴场景要避免的形态。
 */
public class PersonaSubAgent implements SubAgentHandler {

    /** 人设子智能体的优先级。 */
    public static final int PRIORITY = SubAgentArbitrator.PRIORITY_PERSONA;

    /** 人设类意图。 */
    public static final String INTENT_PERSONA = "persona";

    /** 人设卡。 */
    private final PersonaCard personaCard;

    /** 画像存储。 */
    private final com.company.bj.voice.cloud.memory.companion.UserProfileStore profileStore;

    /**
     * 构造角色扮演子智能体。
     *
     * @param personaCard   人设卡
     * @param profileStore 画像存储
     */
    public PersonaSubAgent(
        PersonaCard personaCard,
        com.company.bj.voice.cloud.memory.companion.UserProfileStore profileStore) {
        this.personaCard = personaCard;
        this.profileStore = profileStore;
    }

    @Override
    public SubAgentResult handle(SubAgentRequest request) {
        UserProfile profile = profileStore.load(personaCard.scopeKey());
        String address = profile.preferredAddress();

        String greeting = address.isBlank()
            ? personaCard.defaultGreeting()
            : personaCard.greetingFor(address);

        return SubAgentResult.of(greeting, INTENT_PERSONA, personaCard.emotionTag());
    }

    @Override
    public List<String> supportedIntents() {
        return List.of(INTENT_PERSONA);
    }

    @Override
    public int priority() {
        return PRIORITY;
    }
}
