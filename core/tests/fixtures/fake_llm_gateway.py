"""本地 OpenAI 兼容网关的模拟实现。

用途：在没有真实 API 凭据的情况下，验证"接入大模型后云端回复链路仍然成立"。

**这不是替身测试** —— 它是一个真实的 HTTP 服务，走真实的协议
（POST /chat/completions、Authorization 头、OpenAI 响应体形状），
云端对它发起真实网络请求。区别只在于返回内容是固定文本而非模型生成。

用法：
    F:\\tools\\python313\\python.exe data\\fake_llm_gateway.py [端口]
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

# 模型被允许重写的措辞样本。
GENERATED_TEXT = "记得呀，你妈妈叫李芳，别忘啦。"

# 收到请求的计数，便于外部确认确实被调用过。
REQUEST_COUNT = 0


class Handler(BaseHTTPRequestHandler):
    """模拟 OpenAI 兼容的聊天接口。"""

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        """处理聊天请求。"""
        global REQUEST_COUNT
        REQUEST_COUNT += 1

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

        # 回显收到的内容，便于在云端日志里核对模型确实拿到了记忆内容。
        memory = ""
        for message in payload.get("messages", []):
            content = message.get("content", "")
            if "<memory>" in content:
                memory = content.split("<memory>")[1].split("</memory>")[0].strip()

        body = json.dumps(
            {
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"{GENERATED_TEXT} [收到:{memory}]",
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        """把访问日志写到标准输出，便于在后台进程里查看。"""
        print("[fake-llm] " + fmt % args, flush=True)


def main() -> None:
    """启动模拟网关。"""
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8790
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"[fake-llm] 模拟网关已启动 http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
