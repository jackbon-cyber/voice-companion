# 部署实测用镜像 —— 严格照 docs/operations-manual.md 第 4 章的部署形态
#
# 这个 Dockerfile 不是交付物，是**实测工具**：它验证手册里写的部署步骤
# 在真实的 Linux 容器里能不能跑通。
#
# 形态与手册 4.1 一致：ChromaDB + 云端后端在同一台"服务器"上。
#
# ★ 基础镜像选 python:3.13-slim 是**实测逼出来的**，不是随手选的：
#   手册 1.3 要求 Python 3.13，而 ChromaDB 1.0 要求 Python ≥3.9。
#   ubuntu:20.04 自带 Python 3.8 —— pip 会报
#     "Could not find a version that satisfies the requirement chromadb==1.0.0"
#   （可用版本只到 0.5.23），且**报错信息完全没提 Python 版本**，极易误判为
#   "pip 源有问题"或"版本号写错了"。
#   这就是手册 1.3 那句 "Linux 安装：python3.13" 的真实分量 ——
#   它其实是在说"目标机得有能装 Python 3.13 的发行版"。

FROM python:3.13-slim

# 手册 4.3 要求的软件：curl（健康检查）、ca-certificates（HTTPS）。
#
# ★ build-essential 不是"顺手装的"，是**硬依赖**：
#   chromadb 1.0 会拉入 chroma-hnswlib，它在 Python 3.13 上没有预编译 wheel，
#   必须本地编译。缺编译器时 pip 报的是
#     "RuntimeError: Unsupported compiler -- at least C++11 support is needed!"
#   这句话**极具误导性** —— 它听起来像"装的编译器版本太老"，
#   真相是 slim 镜像里**一个编译器都没有**（gcc/g++/cc/make 全不存在）。
#   排查方向会跑偏到"换个编译器版本"上。
RUN apt-get update -qq \
    && apt-get install -y -qq curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

# JDK 21 —— 手册明确要求 21（用 17 运行会报 class file version 61.0 vs 65.0）。
#
# ★ 下载源是被实测筛出来的，不是随便挑的：
#   Adoptium 官方 API 可达，但它 307 重定向到 GitHub —— GitHub 在本机不可达；
#   华为云 openjdk 镜像实测可下载且 java -version 正常。
#   换网络环境时这一行可能要改，改前请先验证 tar 能解开、java -version 能跑。
ARG JDK_URL=https://mirrors.huaweicloud.com/openjdk/21.0.2/openjdk-21.0.2_linux-x64_bin.tar.gz
RUN mkdir -p /opt/java \
    && curl -fsSL "$JDK_URL" -o /tmp/jdk.tar.gz \
    && tar -xzf /tmp/jdk.tar.gz -C /opt/java --strip-components=1 \
    && rm /tmp/jdk.tar.gz \
    && /opt/java/bin/java -version

ENV JAVA_HOME=/opt/java
ENV PATH=/opt/java/bin:$PATH

# 部署目录 —— 与手册 4.2 的 /opt/voice-companion 对齐
WORKDIR /opt/voice-companion

# 云端后端 jar（fat jar，含全部依赖）
COPY app/voice-cloud.jar /opt/voice-companion/core/cloud/voice-cloud.jar

# 嵌入服务 —— 手册第 0 章要求它与云端同机（云端 8080 调它 8766）。
#
# ★ 只装三个包，不装 requirements.txt 全量：
#   嵌入服务只用标准库 http.server（没有 fastapi/flask），
#   真正需要的只有 numpy / onnxruntime / tokenizers。
#   全量装会拖进 faster-whisper、llama-cpp 等端侧大依赖，
#   部署镜像会从几百 MB 涨到 GB 级，而云端这一侧根本不用它们。
# ★ 版本与本机开发环境一致（numpy 2.2.6 / onnxruntime 1.32.0 / tokenizers 0.23.3），
#   避免"开发能跑、部署跑不出同样结果"。
#   注意：onnxruntime 1.19 在 Python 3.13 上没有 wheel，装不上。
RUN pip install --no-cache-dir \
        "numpy==2.2.6" \
        "onnxruntime==1.32.0" \
        "tokenizers==0.23.3"

# 嵌入模型（BGE-small-zh-v1.5 量化 ONNX，22.9MB）
COPY app/models/embedding /opt/voice-companion/core/models/embedding

# 端侧 Python 包（嵌入服务所在模块树）
COPY app/core /opt/voice-companion/core

# ChromaDB —— 与手册 4.4 的启动方式一致
RUN pip install --no-cache-dir chromadb==1.0.0

# 手册 4.3 的生产环境变量。
# ★ VOICE_UPLINK_TOKEN 必须设置 —— 不设置时上行通道不鉴权，
#   任何能连到端口的客户端都能建会话。
ENV VOICE_UPLINK_TOKEN=deploy-test-token-abc123 \
    VOICE_CHROMA_BASE_URL=http://127.0.0.1:8765 \
    VOICE_CHROMA_DATA_PATH=/opt/voice-companion/data/chroma

EXPOSE 8080 8765

# 手册 4.6 的 systemd 单元在容器里用不了（没有 systemd），
# 这里用等价的启动脚本：先起 Chroma，等就绪，再起云端，等就绪。
COPY start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

CMD ["/usr/local/bin/start.sh"]
