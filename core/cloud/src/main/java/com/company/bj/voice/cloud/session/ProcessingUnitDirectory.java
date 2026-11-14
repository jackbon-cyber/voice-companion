package com.company.bj.voice.cloud.session;

import java.util.List;

/**
 * 处理单元可用性来源。
 *
 * <p><b>为什么需要这个抽象</b>：重路由要回答"除了挂掉的这个单元，还有哪些单元能用"。
 * 第一阶段进程内只有三个逻辑分片，全部可用；但真实部署里处理单元是
 * 独立进程或独立容器，可用性来自注册中心或编排系统。
 *
 * <p>把这部分做成**接口**而不是在调度方法里写
 * {@code if (部署形态 == 容器)}，是为了让"可用单元列表"这个概念稳定下来，
 * 新增部署形态时只需新增一个实现，不改动重路由逻辑。
 */
public interface ProcessingUnitDirectory {

    /**
     * 查询当前可用的处理单元。
     *
     * @return 可用单元标识列表
     */
    List<String> availableUnits();

    /**
     * 查询某个处理单元是否可用。
     *
     * @param unitId 单元标识
     * @return 可用时为 true
     */
    default boolean isAvailable(String unitId) {
        return availableUnits().contains(unitId);
    }
}
