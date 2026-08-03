"""飞书通知:两种发送方式。

- send_lark:走自建应用 SDK(lark-oapi),主动发消息到 open_id/chat_id —— 盘中告警主用。
  用自建飞书应用凭证(同 app 下 open_id 一致),可私聊推送到本人。
- send_feishu:自定义机器人 webhook(备用,只能发机器人所在群,无需应用凭证)。
"""

import json
import logging
import urllib.request

log = logging.getLogger(__name__)

_client = None


def _client_or_none():
    """惰性建 lark 客户端;凭证缺失或 lark-oapi 未装返回 None。"""
    global _client
    if _client is not None:
        return _client
    from ..config import CONFIG

    if not (CONFIG.feishu_app_id and CONFIG.feishu_app_secret):
        return None
    try:
        import lark_oapi as lark
    except ImportError:
        log.error("未安装 lark-oapi,无法用应用 SDK 发消息")
        return None
    _client = (
        lark.Client.builder()
        .app_id(CONFIG.feishu_app_id)
        .app_secret(CONFIG.feishu_app_secret)
        .build()
    )
    return _client


def send_lark(text: str, target: str | None = None) -> bool:
    """自建应用主动发文本消息。

    target 为 open_id(ou_ 开头,发私聊)或群 chat_id(oc_ 开头);缺省用 CONFIG.feishu_target。
    凭证/目标缺失则跳过并返回 False。
    """
    from ..config import CONFIG

    target = target or CONFIG.feishu_target
    client = _client_or_none()
    if client is None or not target:
        log.warning("飞书应用未配置(app_id/secret/target 缺失),跳过通知:%s", text[:40])
        return False

    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

    receive_id_type = _receive_id_type(target)
    body = (
        CreateMessageRequestBody.builder()
        .receive_id(target)
        .msg_type("text")
        .content(json.dumps({"text": text}, ensure_ascii=False))
        .build()
    )
    req = CreateMessageRequest.builder().receive_id_type(receive_id_type).request_body(body).build()
    try:
        resp = client.im.v1.message.create(req)
    except Exception as e:  # noqa: BLE001
        log.error("飞书通知异常: %s", e)
        return False
    if not resp.success():
        log.error("飞书通知失败: code=%s msg=%s", resp.code, resp.msg)
        return False
    log.info("飞书通知已发送: %s", text[:40])
    return True


def _receive_id_type(target: str) -> str:
    """ou_=私聊 open_id;on_=union_id(跨同租户应用一致,复用他 app 凭证发本人时用);其余按群 chat_id。"""
    if target.startswith("ou_"):
        return "open_id"
    if target.startswith("on_"):
        return "union_id"
    return "chat_id"


def send_lark_image(image_path: str, target: str | None = None) -> bool:
    """自建应用发图片消息(先上传拿 image_key 再发)。用于盘后推复盘海报。

    凭证/目标缺失、文件不存在或接口失败均返回 False(不抛,避免拖垮定时任务)。
    """
    import os

    from ..config import CONFIG

    target = target or CONFIG.feishu_target
    client = _client_or_none()
    if client is None or not target:
        log.warning("飞书应用未配置,跳过图片推送:%s", image_path)
        return False
    if not os.path.exists(image_path):
        log.error("海报文件不存在,跳过推送: %s", image_path)
        return False

    from lark_oapi.api.im.v1 import (
        CreateImageRequest,
        CreateImageRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    try:
        with open(image_path, "rb") as f:
            up = client.im.v1.image.create(
                CreateImageRequest.builder()
                .request_body(CreateImageRequestBody.builder().image_type("message").image(f).build())
                .build()
            )
        if not up.success() or not up.data or not up.data.image_key:
            log.error("图片上传失败: code=%s msg=%s", up.code, up.msg)
            return False

        body = (
            CreateMessageRequestBody.builder()
            .receive_id(target)
            .msg_type("image")
            .content(json.dumps({"image_key": up.data.image_key}))
            .build()
        )
        resp = client.im.v1.message.create(
            CreateMessageRequest.builder()
            .receive_id_type(_receive_id_type(target))
            .request_body(body)
            .build()
        )
    except Exception as e:  # noqa: BLE001
        log.error("飞书图片推送异常: %s", e)
        return False
    if not resp.success():
        log.error("飞书图片推送失败: code=%s msg=%s", resp.code, resp.msg)
        return False
    log.info("飞书海报已推送: %s", image_path)
    return True


def send_feishu(webhook: str, text: str) -> bool:
    """自定义机器人 webhook 发文本(备用;只能发机器人所在群)。"""
    if not webhook:
        log.warning("未配置 FEISHU_WEBHOOK,跳过通知:%s", text)
        return False
    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        req = urllib.request.Request(
            webhook,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", "ignore")
        log.info("飞书通知已发送: %s", text[:40])
        return '"code":0' in body or '"StatusCode":0' in body or resp.status == 200
    except Exception as e:  # noqa: BLE001
        log.error("飞书通知失败: %s", e)
        return False
