import os

from api.pid_data_mgr.file_db_models import PIDDataFile
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
        block_file_path = FileStoreService.get_block_file_path(fid, block_name)
        
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
            block_file_path = FileStoreService.get_block_file_path(fid, block_name)
            os.remove(block_file_path)
        except:
            pass

    @staticmethod
    def delete_file_directory(fid: int) -> None:
        """
        删除fid目录及其下所有文件
        
        Args:
            fid: 文件ID
        """
        import shutil
        
        try:
            storage_path = settings.get_storage_path()
            fid_dir = os.path.join(storage_path, str(fid))
            
            # 如果目录存在，则删除整个目录
            if os.path.exists(fid_dir) and os.path.isdir(fid_dir):
                shutil.rmtree(fid_dir)
        except Exception as e:
            # 静默失败，不影响业务流程
            pass

    @staticmethod
    def get_block_file_path(fid: int, block_name: str) -> str:
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

    @staticmethod
    def merge_blocks(file: PIDDataFile, block_names: list[str]):
        """
        合并文件块为文件

        Args:
            file: 文件对象
            block_names: 文件块名称列表
        """
        # 生成合并后的文件路径
        merged_file_path_tmp = os.path.join(settings.get_storage_path(), str(file.fid), file.upload_id, ".tmp")

        # 删除临时文件(可能不存在)
        try:
            os.remove(merged_file_path_tmp)
        except Exception as e:
            pass

        merged_file_path = os.path.join(settings.get_storage_path(), str(file.fid), file.upload_id)
        # 合并文件块
        with open(merged_file_path_tmp, 'wb') as merged_file:
            for block_name in block_names:
                block_path = FileStoreService.get_block_file_path(file.fid, block_name)

                if not os.path.exists(block_path):
                    raise FileNotFoundError(f"文件块不存在: {block_path}")

                # 读取块内容并写入合并文件
                with open(block_path, 'rb') as block_file:
                    merged_file.write(block_file.read())
        # 重命名临时文件
        os.rename(merged_file_path_tmp, merged_file_path)

    @staticmethod
    def clean_file_blocks(file: PIDDataFile):
        """
        清理文件的所有块，保留合并后的文件
        
        Args:
            file: 文件对象
        """
        try:
            # 获取存储路径
            storage_path = settings.get_storage_path()
            fid_dir = os.path.join(storage_path, str(file.fid))

            if not os.path.exists(fid_dir):
                return

            # 目标文件块名称
            target_block_name = file.upload_id

            # 遍历 fid 目录下的所有文件
            for file_name in os.listdir(fid_dir):
                if file_name == target_block_name:
                    continue
                # 删除文件
                os.remove(os.path.join(fid_dir, file_name))
            
        except Exception as e:
            # 静默失败，不影响业务流程
            pass