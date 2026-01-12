from api.pid_data_mgr.file_db_models import PIDDataFile
from api.pid_data_mgr.file_store_service import FileStoreService
from api.pid_data_mgr.file_settings import settings

if __name__ == '__main__':
    print(settings)
    f = PIDDataFile(fid=1, upload_id='123456')
    FileStoreService.merge_blocks(f, list())
    pass