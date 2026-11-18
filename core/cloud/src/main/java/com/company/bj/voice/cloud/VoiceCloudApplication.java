package com.company.bj.voice.cloud;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * 语音陪伴机器人云端服务入口。
 *
 * <p>{@link ConfigurationPropertiesScan} 让 {@code @ConfigurationProperties} 类
 * 注册为 Bean 并完成属性绑定。此前这些类只是"配置载体"，
 * 运行时链路拿不到它们 —— 表现为长期记忆等能力没有真正接上。
 */
@SpringBootApplication
@ConfigurationPropertiesScan
@EnableScheduling
public class VoiceCloudApplication {

    /**
     * 启动云端服务。
     *
     * @param args 命令行参数
     */
    public static void main(String[] args) {
        SpringApplication.run(VoiceCloudApplication.class, args);
    }
}
