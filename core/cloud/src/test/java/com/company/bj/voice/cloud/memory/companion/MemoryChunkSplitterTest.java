package com.company.bj.voice.cloud.memory.companion;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link MemoryChunkSplitter} 的行为验证。
 *
 * <p><b>为什么这个组件需要独立的单元测试</b>：分片直接决定记忆被切成几条、
 * 每条是否保留语义。切错了不会抛异常，只会让召回变差 ——
 * 属于"错了也不报错"的一类改动，必须用测试把边界钉住。
 */
class MemoryChunkSplitterTest {

    private final MemoryChunkSplitter splitter = new MemoryChunkSplitter();

    @Test
    @DisplayName("短记忆整体作为一个片段，不被拆开")
    void 短记忆不拆分() {
        List<String> chunks = splitter.split("我妈妈叫李芳");

        assertThat(chunks).containsExactly("我妈妈叫李芳");
    }

    @Test
    @DisplayName("长记忆按中文逗号切分成多个片段")
    void 长记忆按逗号拆分() {
        List<String> chunks = splitter.split(
            "我妈妈叫李芳，她很爱我，每天都给我做饭，还总提醒我早点休息");

        assertThat(chunks).containsExactly(
            "我妈妈叫李芳",
            "她很爱我",
            "每天都给我做饭",
            "还总提醒我早点休息");
    }

    @Test
    @DisplayName("英文逗号同样作为分隔符")
    void 英文逗号也拆分() {
        List<String> chunks = splitter.split(
            "我表姐在南京工作,做建筑设计,平日里项目都挺忙的");

        assertThat(chunks).containsExactly(
            "我表姐在南京工作",
            "做建筑设计",
            "平日里项目都挺忙的");
    }

    @Test
    @DisplayName("顿号与分号也是分隔符")
    void 顿号与分号也拆分() {
        List<String> chunks = splitter.split(
            "我养了三只仓鼠，一只叫团子一只叫糯米;还有一只叫芝麻");

        assertThat(chunks).containsExactly(
            "我养了三只仓鼠",
            "一只叫团子一只叫糯米",
            "还有一只叫芝麻");
    }

    @Test
    @DisplayName("切分后不产生空白片段")
    void 不产生空白片段() {
        List<String> chunks = splitter.split("我妈妈叫李芳，，她很爱我，");

        assertThat(chunks).containsExactly("我妈妈叫李芳", "她很爱我");
        assertThat(chunks).noneMatch(String::isBlank);
    }

    @Test
    @DisplayName("过短的片段被丢弃，避免检索噪声")
    void 过短片段被丢弃() {
        List<String> chunks = splitter.split("我妈妈叫李芳，她，很爱我，每天都给我做饭");

        assertThat(chunks).doesNotContain("她");
        assertThat(chunks).contains("我妈妈叫李芳", "很爱我", "每天都给我做饭");
    }

    @Test
    @DisplayName("切不动时退回原句，不强行拆成碎片")
    void 切不动时退回原句() {
        // 只有一个超长片段且没有分隔符 —— 拆开会破坏语义，必须保留原句。
        List<String> chunks = splitter.split("这是一段没有任何标点符号分隔的超长记忆内容需要原样保留下来");

        assertThat(chunks).hasSize(1);
        assertThat(chunks.get(0)).startsWith("这是一段没有任何标点符号");
    }

    @Test
    @DisplayName("空内容返回空列表")
    void 空内容返回空列表() {
        assertThat(splitter.split("")).isEmpty();
        assertThat(splitter.split("   ")).isEmpty();
        assertThat(splitter.split(null)).isEmpty();
    }

    @Test
    @DisplayName("首尾空白被裁掉")
    void 裁掉首尾空白() {
        // 长度必须超过单片段上限（12 字），否则整体作为一个片段，
        // 裁掉的只是首尾空白而不是分段。
        List<String> chunks = splitter.split("  我妈妈叫李芳，她很爱我，每天都给我做饭  ");

        assertThat(chunks).containsExactly("我妈妈叫李芳", "她很爱我", "每天都给我做饭");
    }
}
