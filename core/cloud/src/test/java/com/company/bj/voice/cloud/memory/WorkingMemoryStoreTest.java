package com.company.bj.voice.cloud.memory;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;
import java.util.NoSuchElementException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * 工作记忆的任务项生命周期验证。
 *
 * <p>工作记忆保存「正在做的事」——一组带状态的任务项，状态在
 * {@code TODO → IN_PROGRESS → DONE} 之间流转。
 */
class WorkingMemoryStoreTest {

    private ScopeResolver resolver;
    private WorkingMemoryStore store;
    private MemoryScope scope;

    @BeforeEach
    void 准备存储() {
        resolver = new ScopeResolver();
        store = new WorkingMemoryStore(resolver);
        scope = MemoryScope.of("t1", "u1");
    }

    @Test
    void 任务状态可流转() {
        TaskItem created = resolver.withScopeResult(scope, () -> store.addTask("巡检配电室"));
        assertThat(created.status()).isEqualTo(TaskItem.Status.TODO);

        TaskItem inProgress = resolver.withScopeResult(scope,
            () -> store.updateStatus(created.id(), TaskItem.Status.IN_PROGRESS));
        assertThat(inProgress.status()).isEqualTo(TaskItem.Status.IN_PROGRESS);

        TaskItem done = resolver.withScopeResult(scope,
            () -> store.updateStatus(created.id(), TaskItem.Status.DONE));
        assertThat(done.status()).isEqualTo(TaskItem.Status.DONE);
        assertThat(resolver.withScopeResult(scope, () -> store.task(created.id()))).contains(done);
    }

    @Test
    void 列出全部任务项且标识互不相同() {
        resolver.withScopeResult(scope, () -> store.addTask("任务一"));
        resolver.withScopeResult(scope, () -> store.addTask("任务二"));
        resolver.withScopeResult(scope, () -> store.addTask("任务三"));

        List<TaskItem> tasks = resolver.withScopeResult(scope, store::tasks);
        assertThat(tasks).hasSize(3);
        assertThat(tasks).extracting(TaskItem::id).doesNotHaveDuplicates();
        assertThat(tasks).extracting(TaskItem::description)
            .containsExactlyInAnyOrder("任务一", "任务二", "任务三");
    }

    @Test
    void 更新不存在任务的状态时抛出异常() {
        assertThatThrownBy(() -> resolver.withScopeResult(scope,
            () -> store.updateStatus("missing-id", TaskItem.Status.DONE)))
            .isInstanceOf(NoSuchElementException.class);
    }

    @Test
    void 任务项按作用域隔离() {
        resolver.withScopeResult(scope, () -> store.addTask("属于用户一"));
        resolver.withScopeResult(MemoryScope.of("t1", "u2"), () -> store.addTask("属于用户二"));

        List<TaskItem> inFirst = resolver.withScopeResult(scope, store::tasks);
        List<TaskItem> inSecond = resolver.withScopeResult(MemoryScope.of("t1", "u2"), store::tasks);

        assertThat(inFirst).extracting(TaskItem::description).containsExactly("属于用户一");
        assertThat(inSecond).extracting(TaskItem::description).containsExactly("属于用户二");
    }
}

