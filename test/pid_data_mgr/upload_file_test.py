import os
import hashlib
import requests

def upload_file_in_chunks(file_path: str, base_url: str, chunk_size: int = 1024*1024) -> bool:
    """
    将文件分割成指定大小的块并通过HTTP上传到服务器

    Args:
        file_path: 要上传的文件路径
        base_url: 服务器基础URL (例如: http://localhost:8000)
        chunk_size: 每个块的大小，默认1MB

    Returns:
        bool: 上传成功返回True，失败返回False
    """

    # 1. 首先创建上传任务
    file_size = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)

    create_url = f"{base_url}/api/v1/history/data/files"
    create_data = {
        "file_name": file_name,
        "file_size": file_size,
        "desc": "File uploaded in chunks"
    }

    response = requests.post(create_url, json=create_data)
    if response.status_code != 200:
        print(f"创建上传任务失败: {response.text}")
        return False

    create_response = response.json()
    upload_id = create_response["data"]["upload_id"]
    block_size = create_response["data"]["block_size"]
    expected_blocks = create_response["data"]["block_list"]

    print(f"创建上传任务成功，upload_id: {upload_id}, 块大小: {block_size}, 总块数: {len(expected_blocks)}")

    # 2. 按块上传文件
    with open(file_path, 'rb') as f:
        block_id = 0

        while True:
            # 读取一块数据
            chunk_data = f.read(chunk_size)
            if not chunk_data:
                break

            # 计算MD5
            md5_hash = hashlib.md5(chunk_data).hexdigest()

            # 构建上传URL
            upload_chunk_url = f"{base_url}/api/v1/history/data/files"
            params = {
                "upload_id": upload_id,
                "block_id": block_id,
                "md5": md5_hash
            }

            # 创建文件对象进行上传
            from io import BytesIO
            file_obj = BytesIO(chunk_data)

            files = {
                'file': (f'chunk_{block_id}', file_obj, 'application/octet-stream')
            }

            response = requests.put(upload_chunk_url, params=params, files=files)

            if response.status_code != 200:
                print(f"上传块 {block_id} 失败: {response.text}")
                return False

            print(f"块 {block_id} 上传成功")
            block_id += 1

    print(f"文件 {file_name} 上传完成！总共上传了 {block_id} 个块")
    return True


def calculate_file_md5(file_path: str) -> str:
    """
    计算文件的MD5值

    Args:
        file_path: 文件路径

    Returns:
        str: 文件的MD5值
    """
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def split_and_upload_file(file_path: str, base_url: str, chunk_size: int = 1024*1024):
    """
    分割并上传文件的主函数

    Args:
        file_path: 要上传的文件路径
        base_url: 服务器基础URL
        chunk_size: 每个块的大小，默认1MB
    """
    print(f"开始上传文件: {file_path}")
    print(f"文件大小: {os.path.getsize(file_path)} 字节")

    success = upload_file_in_chunks(file_path, base_url, chunk_size)

    if success:
        print("文件上传成功！")
    else:
        print("文件上传失败！")


# 使用示例
if __name__ == "__main__":
    # 配置参数
    # 替换为你要上传的文件路径
    file_to_upload = "D:/test_aa_2026_01_07.csv"
    # file_to_upload = "D:/杂项/timescaledb/tutorial_sample_tick.csv"
    server_base_url = "http://127.0.0.1:8001"  # 替换为你的服务器地址
    chunk_size = 1024 * 1024  # 1MB per chunk

    # 执行上传
    split_and_upload_file(file_to_upload, server_base_url, chunk_size)
