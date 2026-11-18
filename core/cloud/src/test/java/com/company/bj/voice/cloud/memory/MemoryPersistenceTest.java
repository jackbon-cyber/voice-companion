package com.company.bj.voice.cloud.memory;

import static org.assertj.core.api.Assertions.assertThat;

import com.company.bj.voice.cloud.config.MemoryProperties;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * 工作记忆与情景记忆的持久化验证。
 *
 * <p>验证方式刻意模拟<b>进程重启</b>：写入后<b>新建</b>一个 store 实例
 * （不是复用原实例），读回的内容必须与写入时完全一致。
 * 复用原实例的断言证明不了任何东西 —— 内存里的数据本来就在。
 *
 * <p>持久化文件落在临时目录，避免污染工作区的 {@code data/} 目录。
 */
class MemoryPersistenceTest {

    @TempDir
    Path tempDir;

    private MemoryProperties properties;
    private ScopeResolver resolver;
    private MemoryScope scope;

    @BeforeEach
    void 准备配置() {
        properties = new MemoryProperties();
        properties.setDataPath(tempDir.toString());
        properties.setWorkingMemoryFile("working.json");
        properties.setEpisodicMemoryFile("episodic.json");
        resolver = new ScopeResolver();
        scope = MemoryScope.of("t1", "u1");
    }

    @Test
    void 工作记忆在重启后恢复() {
        WorkingMemoryStore before = new WorkingMemoryStore(resolver, properties);
        resolver.withScopeResult(scope, () -> before.addTask("巡检配电室"));
        resolver.withScopeResult(scope, () -> before.addTask("登记缺陷"));

        // 新建实例模拟重启：只从磁盘读取，不复用内存中的实例。
        WorkingMemoryStore after = new WorkingMemoryStore(resolver, properties);

        List<TaskItem> tasks = resolver.withScopeResult(scope, after::tasks);
        assertThat(tasks).hasSize(2);
        assertThat(tasks).extracting(TaskItem::description)
            .containsExactlyInAnyOrder("巡检配电室", "登记缺陷");
        assertThat(tasks).allSatisfy(task -> assertThat(task.status()).isEqualTo(TaskItem.Status.TODO));
        assertThat(tasks).extracting(TaskItem::id).doesNotHaveDuplicates();
    }

    @Test
    void 工作记忆在重启后保留状态流转() {
        WorkingMemoryStore before = new WorkingMemoryStore(resolver, properties);
        TaskItem created = resolver.withScopeResult(scope, () -> before.addTask("巡检配电室"));
        resolver.withScopeResult(scope, () -> before.updateStatus(created.id(), TaskItem.Status.DONE));

        WorkingMemoryStore after = new WorkingMemoryStore(resolver, properties);

        TaskItem restored = resolver.withScopeResult(scope, () -> after.task(created.id())).orElseThrow();
        assertThat(restored.status()).isEqualTo(TaskItem.Status.DONE);
    }

    @Test
    void 情景记忆在重启后恢复() {
        EpisodicMemoryStore before = new EpisodicMemoryStore(resolver, properties);
        Episode episode = resolver.withScopeResult(scope,
            () -> before.record("巡检", List.of("到达现场", "读取电表", "登记结果")));

        // 新建实例模拟重启。
        EpisodicMemoryStore after = new EpisodicMemoryStore(resolver, properties);

        List<Episode> episodes = resolver.withScopeResult(scope, after::episodes);
        assertThat(episodes).hasSize(1);
        assertThat(episodes.get(0).id()).isEqualTo(episode.id());
        assertThat(episodes.get(0).type()).isEqualTo("巡检");
        assertThat(episodes.get(0).events()).containsExactly("到达现场", "读取电表", "登记结果");
        assertThat(episodes.get(0).scope()).isEqualTo(scope);
        assertThat(episodes.get(0).occurredAt()).isEqualTo(episode.occurredAt());
    }

    @Test
    void 持久化文件落在配置指定的位置() throws IOException {
        WorkingMemoryStore working = new WorkingMemoryStore(resolver, properties);
        EpisodicMemoryStore episodic = new EpisodicMemoryStore(resolver, properties);
        resolver.withScopeResult(scope, () -> working.addTask("落盘校验"));
        resolver.withScopeResult(scope, () -> episodic.record("巡检", List.of("事件")));

        // 文件名由「配置的文件名 + 作用域标识」拼成，落在 data-path 下的分层目录中。
        Path workingFile = tempDir.resolve("working-memory")
            .resolve(WorkingMemoryStore.scopeFileName(properties.getWorkingMemoryFile(), scope));
        Path episodicFile = tempDir.resolve("episodic-memory")
            .resolve(EpisodicMemoryStore.scopeFileName(properties.getEpisodicMemoryFile(), scope));

        assertThat(Files.exists(workingFile)).isTrue();
        assertThat(Files.exists(episodicFile)).isTrue();
        assertThat(Files.readString(workingFile)).contains("落盘校验");
        assertThat(Files.readString(episodicFile)).contains("巡检");
    }

    @Test
    void 重启后其他作用域看不到已持久化的情景() {
        EpisodicMemoryStore before = new EpisodicMemoryStore(resolver, properties);
        resolver.withScopeResult(scope, () -> before.record("巡检", List.of("事件")));

        EpisodicMemoryStore after = new EpisodicMemoryStore(resolver, properties);

        List<Episode> episodes = resolver.withScopeResult(
            MemoryScope.of("t1", "u2"), after::episodes);
        assertThat(episodes).isEmpty();
    }
}

