#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ima_cos_upload.py — 把 create_media 返回的 COS 临时凭证，把本地文件 PUT 到腾讯云 COS。

这是「记忆 ⇄ IMA 知识库」真实桥接的最后一步：
agent 调 IMA MCP create_media → 得到 cos_credential + media_id
→ 本脚本用 cos_credential 把文件上传到 COS
→ agent 再调 IMA MCP add_knowledge(media_id) 入库

上传统一走官方 cos-python-sdk-v5（已处理 STS token 与 v5 签名），
不再手工拼签名——手工签名在 IMA 下发的 STS 凭证下会稳定触发
SignatureDoesNotMatch（2026-08-01 实测，4 种手签变体均失败，官方 SDK 一次成功）。

依赖：pip install cos-python-sdk-v5（仅 IMA 桥接用到，离线记忆系统不受影响）。
用法：
python ima_cos_upload.py <creds.json> <本地文件.md> <content_type>
creds.json = {"cos_credential": {...}, "media_id": "..."}  （来自 create_media 返回）
"""
import sys
import json

try:
    from qcloud_cos import CosConfig, CosS3Client
except ImportError:
    print("ERR: 缺少依赖 cos-python-sdk-v5，请先 `pip install cos-python-sdk-v5`")
    sys.exit(2)


def main():
    if len(sys.argv) != 4:
        print("用法: python ima_cos_upload.py <creds.json> <file> <content_type>")
        sys.exit(2)
    creds_path, file_path, content_type = sys.argv[1], sys.argv[2], sys.argv[3]
    # S5 修复：外部 creds.json（来自 IMA MCP create_media）可能带 BOM（Windows 编辑器/某些工具导出），
    # 用 utf-8-sig 容错，避免 json.load 因首字符 BOM 报 "Unexpected character"。
    with open(creds_path, encoding="utf-8-sig") as f:
        c = json.load(f)
    cos = c["cos_credential"]

    config = CosConfig(
        Region=cos["region"],
        SecretId=cos["secret_id"],
        SecretKey=cos["secret_key"],
        Token=cos["token"],
    )
    client = CosS3Client(config)

    with open(file_path, "rb") as f:
        data = f.read()
    try:
        resp = client.put_object(
            Bucket=cos["bucket_name"],
            Body=data,
            Key=cos["cos_key"],
            ContentType=content_type,
        )
        print("UPLOAD_OK media_id=%s etag=%s" % (c.get("media_id", "?"), resp.get("ETag")))
    except Exception as e:  # noqa
        print("UPLOAD_FAIL %s %s" % (type(e).__name__, str(e)[:600]))
        sys.exit(1)


if __name__ == "__main__":
    main()
