package com.company.bj.voice.cloud.memory;

/**
 * 记忆作用域解析器。
 *
 * <p>把「当前这次请求属于哪个租户与主体」这件事从<b>方法入参</b>里拿出来，
 * 放进一个<b>执行上下文</b>。这样做的收益是：任何记忆读写接口都
 * <b>不可能</b>因为调用方漏传作用域而越权读写 —— 因为接口根本不接受作用域参数。
 *
 * <p>实现基于 {@link ThreadLocal}，因此作用域在<b>同一线程内</b>可见，
 * 跨线程不可见。这是有意的取舍：
 * <ul>
 *   <li>绝大多数场景（Controller → Service）在同一线程内完成，不需要额外传递；</li>
 *   <li>异步场景（响应式、线程池）需要显式传递上下文，属于调用方的责任，
 *       后续可通过包装器补齐。</li>
 * </ul>
 *
 * <p><b>嵌套支持</b>：{@link #withScope} 在 {@code finally} 中恢复<b>前一个</b>作用域，
 * 因此内层作用域退出后自动回到外层作用域，不会「泄漏」到外层。
 */
public class ScopeResolver {

    /** 当前线程的作用域。 */
    private final ThreadLocal<MemoryScope> current = new ThreadLocal<>();

    /**
     * 读取当前作用域。
     *
     * @return 当前作用域
     * @throws IllegalStateException 当前线程没有活动作用域时抛出，
     *                               消息固定为 {@code no active memory scope}
     */
    public MemoryScope current() {
        MemoryScope scope = current.get();
        if (scope == null) {
            throw new IllegalStateException("no active memory scope");
        }
        return scope;
    }

    /**
     * 在指定作用域下执行一段逻辑，执行完毕后恢复原作用域。
     *
     * <p>恢复动作放在 {@code finally} 中：被执行的逻辑抛异常时，
     * 作用域同样必须被恢复，否则一次失败就会把线程的作用域「弄脏」，
     * 后续操作会以错误的作用域执行。
     *
     * @param scope  作用域，为 {@code null} 时抛出 {@link IllegalArgumentException}
     * @param action 待执行的逻辑
     * @throws IllegalArgumentException 作用域为 {@code null} 时抛出
     */
    public void withScope(MemoryScope scope, Runnable action) {
        if (scope == null) {
            throw new IllegalArgumentException("memory scope must not be null");
        }
        MemoryScope previous = current.get();
        current.set(scope);
        try {
            action.run();
        } finally {
            if (previous == null) {
                current.remove();
            } else {
                current.set(previous);
            }
        }
    }

    /**
     * 在指定作用域下执行一段有返回值的逻辑，执行完毕后恢复原作用域。
     *
     * <p>本方法<b>刻意不叫</b> {@code withScope}：与 {@link #withScope(MemoryScope, Runnable)}
     * 同名会让「返回值的 lambda」在编译期产生重载歧义
     * （{@code Runnable} 与 {@code Supplier} 都能匹配返回值的表达式），
     * 调用方被迫显式转型才能编译。改名换来的是无歧义的调用体验。
     *
     * @param scope  作用域，为 {@code null} 时抛出 {@link IllegalArgumentException}
     * @param action 待执行的逻辑
     * @param <T>    返回值类型
     * @return 逻辑的返回值
     * @throws IllegalArgumentException 作用域为 {@code null} 时抛出
     */
    public <T> T withScopeResult(MemoryScope scope, java.util.function.Supplier<T> action) {
        if (scope == null) {
            throw new IllegalArgumentException("memory scope must not be null");
        }
        MemoryScope previous = current.get();
        current.set(scope);
        try {
            return action.get();
        } finally {
            if (previous == null) {
                current.remove();
            } else {
                current.set(previous);
            }
        }
    }
}
