package com.company.bj.voice.cloud.memory;

/**
 * 工作记忆中的任务项。
 *
 * <p>工作记忆保存「正在做的事」，一个任务项就是一件待办事的当前状态。
 * 状态在 {@link Status} 的三个取值之间流转。
 *
 * @param id          任务标识
 * @param description 任务描述
 * @param status      当前状态
 * @param createdAt   创建时间戳（epoch 毫秒）
 */
public record TaskItem(String id, String description, Status status, long createdAt) {

    /**
     * 任务状态。
     */
    public enum Status {

        /** 待处理。 */
        TODO,

        /** 进行中。 */
        IN_PROGRESS,

        /** 已完成。 */
        DONE
    }
}
