from __future__ import annotations

import json
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Protocol

mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("application/x-subrip", ".srt")


class Storage(Protocol):
    name: str

    def put(self, path: Path, key: str) -> str: ...

    def get_text(self, key: str) -> str | None: ...

    def put_text(self, text: str, key: str, content_type: str = "application/json") -> str: ...


class LocalStorage:
    def __init__(self, root: Path, public_base_url: str | None = None):
        self.root = root
        self.public_base_url = public_base_url
        self.name = f"local:{root}"

    def put(self, path: Path, key: str) -> str:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.copyfile(path, tmp)
        os.replace(tmp, dest)
        return self.url(key)

    def get_text(self, key: str) -> str | None:
        path = self._path(key)
        return path.read_text() if path.exists() else None

    def put_text(self, text: str, key: str, content_type: str = "application/json") -> str:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
        return self.url(key)

    def url(self, key: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{key}"
        return self._path(key).resolve().as_uri()

    def _path(self, key: str) -> Path:
        dest = (self.root / key).resolve()
        if not dest.is_relative_to(self.root.resolve()):
            raise ValueError(f"Key escapes storage root: {key!r}")
        return dest


class S3Storage:
    """Any S3-compatible bucket: AWS S3, Cloudflare R2, MinIO, GCS interoperability."""

    def __init__(self, bucket: str, prefix: str = "", endpoint_url: str | None = None,
                 public_base_url: str | None = None, client=None):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.public_base_url = public_base_url
        self._client = client
        self._endpoint_url = endpoint_url
        self.name = f"s3:{bucket}/{self.prefix}"

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", endpoint_url=self._endpoint_url)
        return self._client

    def put(self, path: Path, key: str) -> str:
        full = self._key(key)
        self.client.upload_file(str(path), self.bucket, full, ExtraArgs={"ContentType": _content_type(path.name)})
        return self.url(key)

    def get_text(self, key: str) -> str | None:
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read()
        except self.client.exceptions.NoSuchKey:
            return None
        return body.decode()

    def put_text(self, text: str, key: str, content_type: str = "application/json") -> str:
        self.client.put_object(Bucket=self.bucket, Key=self._key(key), Body=text.encode(),
                               ContentType=f"{content_type}; charset=utf-8")
        return self.url(key)

    def url(self, key: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{self._key(key)}"
        return f"s3://{self.bucket}/{self._key(key)}"

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key


def storage_from_env(env: dict | None = None) -> Storage:
    env = os.environ if env is None else env
    kind = env.get("PD_STORAGE", "local")
    if kind == "local":
        return LocalStorage(Path(env.get("PD_LOCAL_ROOT", "published")), env.get("PD_PUBLIC_BASE_URL"))
    if kind == "s3":
        return S3Storage(
            bucket=env["PD_S3_BUCKET"],
            prefix=env.get("PD_S3_PREFIX", ""),
            endpoint_url=env.get("PD_S3_ENDPOINT_URL"),
            public_base_url=env.get("PD_PUBLIC_BASE_URL"),
        )
    raise ValueError(f"Unknown PD_STORAGE {kind!r}; use 'local' or 's3'")


def _content_type(name: str) -> str:
    guessed, _ = mimetypes.guess_type(name)
    if guessed and guessed.startswith("text/"):
        return f"{guessed}; charset=utf-8"
    return guessed or "application/octet-stream"


def read_json(storage: Storage, key: str, default):
    text = storage.get_text(key)
    return json.loads(text) if text else default
