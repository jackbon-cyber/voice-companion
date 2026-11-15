package com.company.bj.voice.cloud.agent;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

/**
 * 人设卡。
 *
 * <p>结构化定义（不是一段自由文本），这样才能<b>版本化 + 热更</b>：
 * 改了人设就换一版，下一轮生效，旧的版本仍可回滚。
 *
 * <p><b>热更的实现是"整体替换"而非"原地改字段"</b>：
 * 原地改会让读到一半的请求看到半新半旧的人设 ——
 * 表现为机器人一句话里前半句是新语气、后半句是旧语气。
 * 用 {@link AtomicReference} 整体换引用，读到的永远是完整的一版。
 */
public class PersonaCard {

    /** 人设版本。 */
    private final String version;

    /** 陪伴者名字。 */
    private final String name;

    /** 默认问候语（未识别到用户称呼时使用）。 */
    private final String defaultGreeting;

    /** 称呼到问候语的映射模板。 */
    private final java.util.Map<String, String> greetings;

    /** 情感标签。 */
    private final String emotionTag;

    /** 人设卡的作用域键。 */
    private final String scopeKey;

    /**
     * 构造人设卡。
     *
     * @param version         人设版本
     * @param name            陪伴者名字
     * @param defaultGreeting 默认问候语
     * @param greetings       称呼到问候语的映射
     * @param emotionTag      情感标签
     * @param scopeKey        作用域键
     */
    public PersonaCard(
        String version,
        String name,
        String defaultGreeting,
        java.util.Map<String, String> greetings,
        String emotionTag,
        String scopeKey) {
        this.version = version;
        this.name = name;
        this.defaultGreeting = defaultGreeting;
        this.greetings = java.util.Map.copyOf(greetings);
        this.emotionTag = emotionTag;
        this.scopeKey = scopeKey;
    }

    /**
     * 返回面向某称呼的问候语。
     *
     * @param address 用户称呼
     * @return 问候语；没有专属问候语时返回默认问候语
     */
    public String greetingFor(String address) {
        return greetings.getOrDefault(address, defaultGreeting);
    }

    /**
     * 返回人设版本。
     *
     * @return 版本标识
     */
    public String version() {
        return version;
    }

    /**
     * 返回陪伴者名字。
     *
     * @return 名字
     */
    public String name() {
        return name;
    }

    /**
     * 返回默认问候语。
     *
     * @return 问候语
     */
    public String defaultGreeting() {
        return defaultGreeting;
    }

    /**
     * 返回情感标签。
     *
     * @return 情感标签
     */
    public String emotionTag() {
        return emotionTag;
    }

    /**
     * 返回作用域键。
     *
     * @return 作用域键
     */
    public String scopeKey() {
        return scopeKey;
    }

    /**
     * 返回该人设支持的全部称呼。
     *
     * @return 称呼列表
     */
    public List<String> knownAddresses() {
        return List.copyOf(greetings.keySet());
    }

    /**
     * 人设卡热更持有者。
     *
     * <p>持有一个"当前生效版本"的引用，读操作无锁，
     * 写操作是<b>整体替换</b>——不会出现半新半旧的状态。
     */
    public static class Holder {

        /** 当前生效的人设卡。 */
        private final AtomicReference<PersonaCard> current;

        /**
         * 构造持有者。
         *
         * @param initial 初始人设卡
         */
        public Holder(PersonaCard initial) {
            this.current = new AtomicReference<>(initial);
        }

        /**
         * 读取当前人设卡。
         *
         * @return 当前人设卡
         */
        public PersonaCard current() {
            return current.get();
        }

        /**
         * 切换到新版本。
         *
         * @param card 新的人设卡
         * @return 切换前的人设卡
         */
        public PersonaCard swap(PersonaCard card) {
            if (card == null) {
                throw new IllegalArgumentException("persona card must not be null");
            }
            return current.getAndSet(card);
        }

        /**
         * 从文件加载人设卡。
         *
         * <p>文件格式为纯文本，每行一条，格式为
         * {@code 版本|名字|默认问候|情感标签|作用域键|称呼=问候,称呼=问候}。
         *
         * @param path 人设卡文件路径
         * @return 加载出的人设卡
         * @throws IOException 读取文件失败时抛出
         */
        public static PersonaCard load(Path path) throws IOException {
            List<String> lines = Files.readAllLines(path, StandardCharsets.UTF_8);
            if (lines.isEmpty()) {
                throw new IOException("persona card file is empty: " + path);
            }
            String[] parts = lines.get(0).split("\\|", -1);
            if (parts.length < 6) {
                throw new IOException("persona card format invalid: " + path);
            }
            java.util.Map<String, String> greetings = new java.util.LinkedHashMap<>();
            if (!parts[5].isBlank()) {
                for (String entry : parts[5].split(",")) {
                    String[] pair = entry.split("=", 2);
                    if (pair.length == 2) {
                        greetings.put(pair[0].trim(), pair[1].trim());
                    }
                }
            }
            return new PersonaCard(
                parts[0].trim(), parts[1].trim(), parts[2].trim(),
                greetings, parts[3].trim(), parts[4].trim());
        }
    }
}
