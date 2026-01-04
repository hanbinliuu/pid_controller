from pydantic import BaseModel, Field
import os
import multiprocessing as mp


class Settings(BaseModel):
    """
    应用设置类
    """
    upload_id_length: int = Field(default=36, description="上传ID的长度")

    md5_sum_length: int = Field(default=32, description="MD5校验码的长度")

    # 支持的最大文件大小（字节）
    max_file_size: int = Field(
        default=1 * 1024 * 1024 * 1024,  # 1GB
        description="支持的最大文件大小（字节）"
    )

    # 每个块的大小（字节）
    chunk_size: int = Field(
        default=1 * 1024 * 1024,  # 1MB
        description="每个分块的大小（字节）"
    )

    # 数据存储目录
    storage_dir: str = Field(
        default="./uploads",
        description="文件存储目录路径"
    )

    retention_hours: int = Field(
        default=24 * 7,  # 7天
        description="数据保留时间（小时）"
    )

    host_port: str = Field(
        default="",
        description="服务监听的host和port"
    )

    queue: mp.Queue = Field(
        default=mp.Queue(),
        description="任务队列"
    )

    db_base_url: str = Field(
        default="",
        description="数据库连接地址"
    )

    db_name: str = Field(
        default="",
        description="数据库名称"
    )

    def get_storage_path(self) -> str:
        """
        获取完整的存储路径，确保目录存在

        Returns:
            str: 完整的存储路径
        """
        # 确保目录存在
        os.makedirs(self.storage_dir, exist_ok=True)
        return os.path.abspath(self.storage_dir)


# 创建全局设置实例
settings = Settings()