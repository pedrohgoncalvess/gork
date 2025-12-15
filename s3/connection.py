import asyncio
import base64
import uuid
from io import BytesIO
from typing import Optional, List
from datetime import timedelta

from minio import Minio
from minio.error import S3Error
from PIL import Image

from utils import get_env_var


class S3Client:
    _instance: Optional['S3Client'] = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return

        self._initialized = True
        self.client: Optional[Minio] = None
        self.endpoint: str = ""
        self.buckets_to_create: List[str] = [
            "whatsapp",
        ]

    async def connect(self):
        async with self._lock:
            if self.client is not None:
                return

            endpoint = get_env_var("MINIO_ENDPOINT")
            access_key = get_env_var("MINIO_ACCESS_KEY")
            secret_key = get_env_var("MINIO_SECRET_KEY")
            use_ssl = get_env_var("MINIO_USE_SSL").lower() == "true"

            self.endpoint = f"{'https' if use_ssl else 'http'}://{endpoint}"

            self.client = Minio(
                endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=use_ssl
            )

            await self._setup_buckets()

    async def _setup_buckets(self):
        loop = asyncio.get_event_loop()

        for bucket_name in self.buckets_to_create:
            exists = await loop.run_in_executor(
                None,
                self.client.bucket_exists,
                bucket_name
            )

            if not exists:
                await loop.run_in_executor(
                    None,
                    self.client.make_bucket,
                    bucket_name
                )

    async def get_image_base64(
            self,
            bucket_name: str,
            object_path: str,
    ) -> str:
        """
        Get image as base64 string from MinIO

        Args:
            bucket_name: Bucket name
            object_path: Object path in bucket
            include_data_uri: If True, returns "data:image/...;base64,..."

        Returns:
            Base64 encoded image string
        """
        if not self.client:
            raise RuntimeError("MinIO client not initialized")

        loop = asyncio.get_event_loop()
        object_path = object_path.lstrip('/')

        try:
            response = await loop.run_in_executor(
                None,
                self.client.get_object,
                bucket_name,
                object_path
            )

            image_bytes = response.read()
            response.close()
            response.release_conn()

            base64_string = base64.b64encode(image_bytes).decode('utf-8')

            return base64_string

        except S3Error as e:
            raise Exception(f"Error downloading image from MinIO: {str(e)}")


    async def upload_image(
            self,
            image_source: bytes,
            convert_to_webp: bool = False,
            max_size: tuple[float, float] = (1920, 1920),
            object_name: Optional[str] = None
    ) -> str:
        """
        Upload an image to MinIO

        Args:
            image_source: File path or BytesIO object
            convert_to_webp: Convert image to WebP format
            max_size: Maximum dimensions (width, height)
            object_name: S3 object name (generates UUID if None)

        Returns:
            S3 path in format "bucket:object_name"
        """
        loop = asyncio.get_event_loop()
        bucket_name = "whatsapp"

        image_source = BytesIO(image_source)
        image_source.seek(0)

        img = Image.open(image_source)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

        if convert_to_webp:
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            format_type = 'WEBP'
            extension = 'webp'
            content_type = 'image/webp'
        else:
            format_type = img.format or 'PNG'
            extension = format_type.lower()
            content_type = f'image/{extension}'

        buffer = BytesIO()
        img.save(buffer, format=format_type, quality=95)
        buffer.seek(0)

        if object_name is None:
            object_name = f"{uuid.uuid4()}.{extension}"
        elif not object_name.endswith(f'.{extension}'):
            object_name = f"{object_name}.{extension}"

        await loop.run_in_executor(
            None,
            self.client.put_object,
            bucket_name,
            object_name,
            buffer,
            buffer.getbuffer().nbytes,
            content_type
        )

        return object_name

    async def get_presigned_url(
            self,
            sub_path: str,
            bucket_name: str = "images",
            expires_minutes: int = 30
    ) -> str:
        loop = asyncio.get_event_loop()

        object_path = sub_path.lstrip('/')

        url = await loop.run_in_executor(
            None,
            self.client.presigned_get_object,
            bucket_name,
            object_path,
            timedelta(minutes=expires_minutes)
        )

        return url

    async def get_url_from_path(self, bucket_name: str, object_path: str) -> str:
        """
        Get direct URL for an object (for public buckets)

        Args:
            bucket_name: Bucket name
            object_path: Object path in bucket

        Returns:
            Direct object URL
        """
        object_path = object_path.lstrip('/')
        return f"{self.endpoint}/{bucket_name}/{object_path}"

    async def object_exists(self, bucket_name: str, object_path: str) -> bool:
        """
        Check if an object exists in bucket

        Args:
            bucket_name: Bucket name
            object_path: Object path

        Returns:
            True if object exists, False otherwise
        """
        if not self.client:
            raise RuntimeError("MinIO client not initialized")

        loop = asyncio.get_event_loop()
        object_path = object_path.lstrip('/')

        try:
            await loop.run_in_executor(
                None,
                self.client.stat_object,
                bucket_name,
                object_path
            )
            return True
        except S3Error:
            return False

    async def delete_object(self, bucket_name: str, object_path: str) -> bool:
        """
        Delete an object from bucket

        Args:
            bucket_name: Bucket name
            object_path: Object path

        Returns:
            True if successfully deleted
        """
        loop = asyncio.get_event_loop()
        object_path = object_path.lstrip('/')

        try:
            await loop.run_in_executor(
                None,
                self.client.remove_object,
                bucket_name,
                object_path
            )
            return True
        except S3Error:
            return False