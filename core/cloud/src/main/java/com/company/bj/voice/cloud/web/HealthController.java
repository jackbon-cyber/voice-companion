package com.company.bj.voice.cloud.web;

import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 健康检查端点。
 *
 * <p>启动脚本用它判断后端是否就绪，因此**必须**返回最简信息 ——
 * 健康检查的响应会出现在日志与监控面板里，任何异常堆栈或配置项都不该外泄。
 */
@RestController
@RequestMapping("/api")
public class HealthController {

    /** 健康状态取值。 */
    private static final String STATUS_UP = "UP";

    /**
     * 返回服务健康状态。
     *
     * @return 含状态字段的响应体
     */
    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", STATUS_UP);
    }
}
