# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
from __future__ import annotations

import asyncio
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import boto3


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, *, content_type: str) -> str: ...

    async def get(self, key: str) -> bytes: ...


def validate_key(key: str) -> str:
    path = PurePosixPath(key)
    if not key or path.is_absolute() or ".." in path.parts:
        raise ValueError("object key must be relative and cannot contain traversal")
    return path.as_posix()


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        del content_type
        path = self.root / validate_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return path.as_uri()

    async def get(self, key: str) -> bytes:
        path = self.root / validate_key(key)
        return await asyncio.to_thread(path.read_bytes)


class S3ObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.bucket = bucket
        self.client = client or boto3.client("s3", region_name=region, endpoint_url=endpoint_url)

    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        safe_key = validate_key(key)
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=safe_key,
            Body=data,
            ContentType=content_type,
        )
        return f"s3://{self.bucket}/{safe_key}"

    async def get(self, key: str) -> bytes:
        response = await asyncio.to_thread(
            self.client.get_object, Bucket=self.bucket, Key=validate_key(key)
        )
        return await asyncio.to_thread(response["Body"].read)
