import os
from api.pid_data_mgr.file_settings import settings


class FileStoreService:
    """文件存储服务 - 负责文件块的物理存储操作"""

    @staticmethod
    def write_block(fid: int, block_name: str, data: bytes) -> None:
        """
        将文件块写入磁盘
        
        Args:
            fid: 文件ID
            block_name: 块名称(UUID)
            data: 块数据
            
        Raises:
            Exception: 写入失败时抛出异常
        """
        block_file_path = FileStoreService._get_block_file_path(fid, block_name)
        
        # 确保目录存在
        os.makedirs(os.path.dirname(block_file_path), exist_ok=True)
        
        # 写入文件块
        with open(block_file_path, 'wb') as block_file:
            block_file.write(data)

    @staticmethod
    def delete_block(fid: int, block_name: str) -> None:
        """
        删除文件块
        
        Args:
            fid: 文件ID
            block_name: 块名称(UUID)
        """
        try:
            block_file_path = FileStoreService._get_block_file_path(fid, block_name)
            os.remove(block_file_path)
        except:
            pass

    @staticmethod
    def _get_block_file_path(fid: int, block_name: str) -> str:
        """
        获取文件块的存储路径

        Args:
            fid: 文件ID
            block_name: 块名称(UUID)

        Returns:
            str: 文件块的完整路径
        """
        storage_path = settings.get_storage_path()
        # 使用fid作为子目录，便于管理
        return os.path.join(storage_path, str(fid), block_name)