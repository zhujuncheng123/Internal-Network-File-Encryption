"""启动入口：HTTPS 主服务 + HTTP -> HTTPS 自动跳转。

- 主服务：app.main:app，监听 settings.port（默认 8443），HTTPS。
- 跳转服务：监听 settings.http_port（默认 8080），HTTP，
  任意请求 301 跳转到 https://<host>:<port><path>。
  这样用户输 http:// 或裸地址也会自动进入 https。
"""
import threading

import uvicorn

from config import settings


def _build_redirect_app():
    from starlette.applications import Starlette
    from starlette.responses import RedirectResponse
    from starlette.routing import Route

    async def _redirect(request):
        host = request.headers.get("host", "127.0.0.1")
        hostname = host.split(":")[0]
        # 标准端口不显示端口号
        if settings.port == 443:
            base = f"https://{hostname}"
        else:
            base = f"https://{hostname}:{settings.port}"
        target = base + request.url.path
        if request.url.query:
            target += "?" + request.url.query
        return RedirectResponse(target, status_code=301)

    return Starlette(routes=[Route("/{path:path}", _redirect)])


def _start_redirect():
    from uvicorn import Config as UVConfig
    from uvicorn import Server

    cfg = UVConfig(_build_redirect_app(), host=settings.host,
                   port=settings.http_port, log_level="warning")
    Server(cfg).run()


if __name__ == "__main__":
    if settings.http_redirect_enabled:
        threading.Thread(target=_start_redirect, daemon=True).start()

    kwargs = dict(host=settings.host, port=settings.port)
    if settings.cert_file and settings.key_file:
        kwargs.update(ssl_certfile=settings.cert_file, ssl_keyfile=settings.key_file)
    uvicorn.run("app.main:app", **kwargs)
