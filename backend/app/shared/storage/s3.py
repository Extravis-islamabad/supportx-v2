"""S3-compatible storage with aioboto3 (see the package docstring)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import aioboto3
from aiobotocore.config import AioConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings
from app.core.errors import ServiceUnavailable
from app.core.logging import get_logger

if TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client

log = get_logger(__name__)
_MISSING = {"NoSuchKey", "404", "NotFound"}
# S3 multipart parts must be at least 5 MiB (except the last): the smallest part keeps the memory
# an upload holds as low as S3 allows (one part in flight per upload).
PART_BYTES = 5 << 20
_READ_PIECE = 256 << 10


def _reason(exc: Exception) -> str:
    """The S3 error code or exception class, for the log (never the request or credentials)."""
    if isinstance(exc, ClientError):
        return str(exc.response.get("Error", {}).get("Code", "ClientError"))
    return type(exc).__name__


class StorageUnavailable(ServiceUnavailable):
    """The object store did not answer or refused the request."""

    code = "storage_unavailable"


class StorageNotConfigured(ServiceUnavailable):
    """No object store is configured for this installation."""

    code = "storage_not_configured"


class ObjectStorage(Protocol):
    """What modules may do with object storage."""

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store `data` at `key` (overwrites)."""
        ...

    async def get(self, key: str) -> bytes | None:
        """The object at `key`, or None if there is none."""
        ...

    async def delete(self, key: str) -> None:
        """Remove `key` (no error if it is already gone)."""
        ...

    async def check(self) -> None:
        """Raise `StorageUnavailable` unless the bucket can be reached."""
        ...

    async def put_stream(self, key: str, parts: AsyncIterator[bytes], content_type: str) -> int:
        """Store an object from a stream of parts (multipart above PART_BYTES); bytes written."""
        ...

    def read_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]:
        """Bytes start..end (inclusive) of an object, streamed; `StorageUnavailable` if absent."""
        ...


@dataclass(frozen=True)
class S3Storage:
    """One bucket on an S3-compatible endpoint."""

    endpoint: str
    region: str
    access_key: str
    secret_key: str
    bucket: str
    timeout: float

    @asynccontextmanager
    async def _client(self) -> AsyncIterator["S3Client"]:
        session = aioboto3.Session()
        config = AioConfig(
            connect_timeout=self.timeout,
            read_timeout=self.timeout,
            retries={"max_attempts": 2},
            s3={"addressing_style": "path"},
        )
        async with session.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name=self.region,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=config,
        ) as client:
            yield client

    async def _bucket_exists(self, client: "S3Client") -> None:
        # Like `put`: the bucket is created on first use (a fresh installation or dev stack).
        try:
            await client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code")) not in _MISSING:
                raise
            await client.create_bucket(Bucket=self.bucket)

    async def ensure_bucket(self) -> None:
        """Create the bucket if it does not exist yet (installers and the first start)."""
        try:
            async with self._client() as client:
                try:
                    await client.head_bucket(Bucket=self.bucket)
                except ClientError as exc:
                    if str(exc.response.get("Error", {}).get("Code")) not in _MISSING:
                        raise
                    await client.create_bucket(Bucket=self.bucket)
        except (BotoCoreError, ClientError, OSError) as exc:
            log.warning("storage_unreachable", operation="ensure_bucket")
            raise StorageUnavailable from exc

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store an object (creating the bucket on first use)."""
        try:
            async with self._client() as client:
                try:
                    await client.put_object(
                        Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
                    )
                except ClientError as exc:
                    if str(exc.response.get("Error", {}).get("Code")) != "NoSuchBucket":
                        raise
                    await client.create_bucket(Bucket=self.bucket)
                    await client.put_object(
                        Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
                    )
        except (BotoCoreError, ClientError, OSError) as exc:
            log.warning("storage_unreachable", operation="put")
            raise StorageUnavailable from exc

    async def get(self, key: str) -> bytes | None:
        """Read an object, or None when it does not exist."""
        try:
            async with self._client() as client:
                try:
                    response = await client.get_object(Bucket=self.bucket, Key=key)
                except ClientError as exc:
                    if str(exc.response.get("Error", {}).get("Code")) in _MISSING:
                        return None
                    raise
                async with response["Body"] as body:
                    return await body.read()
        except (BotoCoreError, ClientError, OSError) as exc:
            log.warning("storage_unreachable", operation="get")
            raise StorageUnavailable from exc

    async def delete(self, key: str) -> None:
        """Remove an object."""
        try:
            async with self._client() as client:
                await client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError, OSError) as exc:
            log.warning("storage_unreachable", operation="delete")
            raise StorageUnavailable from exc

    async def put_stream(self, key: str, parts: AsyncIterator[bytes], content_type: str) -> int:
        """Store a stream without holding it in memory: one PUT when small, else multipart.

        A failure part-way aborts the multipart upload, so no half object is left behind.
        """
        pending: list[bytes] = []
        pending_size = 0
        written = 0
        upload_id: str | None = None
        numbers: list[dict[str, object]] = []
        try:
            async with self._client() as client:

                async def send(body: bytes) -> None:
                    nonlocal upload_id
                    if upload_id is None:
                        await self._bucket_exists(client)
                        created = await client.create_multipart_upload(
                            Bucket=self.bucket, Key=key, ContentType=content_type
                        )
                        upload_id = created["UploadId"]
                    number = len(numbers) + 1
                    sent = await client.upload_part(
                        Bucket=self.bucket,
                        Key=key,
                        UploadId=upload_id,
                        PartNumber=number,
                        Body=body,
                    )
                    numbers.append({"PartNumber": number, "ETag": sent["ETag"]})

                async for part in parts:
                    pending.append(part)
                    pending_size += len(part)
                    written += len(part)
                    if pending_size >= PART_BYTES:
                        # One join per part: the pieces are not copied again and again.
                        body = b"".join(pending)
                        pending, pending_size = [], 0
                        await send(body)
                        del body
                if upload_id is None:
                    await self._bucket_exists(client)
                    await client.put_object(
                        Bucket=self.bucket,
                        Key=key,
                        Body=b"".join(pending),
                        ContentType=content_type,
                    )
                    return written
                if pending:
                    await send(b"".join(pending))
                await client.complete_multipart_upload(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": numbers},  # type: ignore[typeddict-item]  # boto stubs want a narrower dict type
                )
                return written
        except (BotoCoreError, ClientError, OSError) as exc:
            log.warning("storage_unreachable", operation="put_stream", error=_reason(exc))
            await self._abort(key, upload_id)
            raise StorageUnavailable from exc
        except BaseException:
            await self._abort(key, upload_id)
            raise

    async def _abort(self, key: str, upload_id: str | None) -> None:
        if upload_id is None:
            return
        try:
            async with self._client() as client:
                await client.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)
        except (BotoCoreError, ClientError, OSError):
            log.warning("storage_unreachable", operation="abort_multipart")

    async def read_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]:
        """Bytes start..end (inclusive), streamed in pieces of at most 256 KiB."""
        try:
            async with self._client() as client:
                response = await client.get_object(
                    Bucket=self.bucket, Key=key, Range=f"bytes={start}-{end}"
                )
                async with response["Body"] as body:  # an aiohttp response underneath
                    async for piece in body.content.iter_chunked(_READ_PIECE):
                        yield piece
        except (BotoCoreError, ClientError, OSError) as exc:
            log.warning("storage_unreachable", operation="read_range")
            raise StorageUnavailable from exc

    async def check(self) -> None:
        """Reach the bucket or raise."""
        try:
            async with self._client() as client:
                await client.head_bucket(Bucket=self.bucket)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise StorageUnavailable from exc


def storage_from(settings: Settings) -> S3Storage:
    """The configured store, or `StorageNotConfigured`."""
    if (
        settings.object_storage_endpoint is None
        or settings.object_storage_access_key is None
        or settings.object_storage_secret_key is None
    ):
        raise StorageNotConfigured
    return S3Storage(
        endpoint=settings.object_storage_endpoint,
        region=settings.object_storage_region,
        access_key=settings.object_storage_access_key.get_secret_value(),
        secret_key=settings.object_storage_secret_key.get_secret_value(),
        bucket=settings.object_storage_bucket,
        timeout=settings.object_storage_timeout_seconds,
    )
