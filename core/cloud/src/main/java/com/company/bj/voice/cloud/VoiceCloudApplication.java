package com.company.bj.voice.cloud;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * 语音陪伴机器人云端服务入口。
 */
@SpringBootApplication
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
