package com.company.bj.voice.cloud.memory;

/**
 * 记忆持久化异常。
 *
 * <p>工作记忆与情景记忆的落盘/读盘失败统一用本异常表达。
 * 它是 {@link RuntimeException} 的子类，调用方无需强制捕获，
 * 但 Spring 默认会把它当作 500 错误处理 —— 这正是期望行为：
 * 记忆写盘失败意味着「本次操作声称成功但其实没存住」，
 * 静默吞掉会让问题在很久之后才暴露。
 */
public class MemoryPersistenceException extends RuntimeException {

    /**
     * 构造异常。
     *
     * @param message 异常消息
     */
    public MemoryPersistenceException(String message) {
        super(message);
    }

    /**
     * 构造异常。
     *
     * @param message 异常消息
     * @param cause   原始异常
     */
    public MemoryPersistenceException(String message, Throwable cause) {
        super(message, cause);
    }
}
