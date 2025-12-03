

# 分析最近1天的数据
from datetime import datetime
from typing import List, Dict

from core.agent.tools import process_query_tsdb_data_interpolated
from core.client.bff_model_client import BFFModelClient
from core.client.real_tsdb_client import get_default_database

def get_history_data(start_time: datetime, end_time: datetime) -> List[Dict]:
    if not start_time:
        start_time = int(datetime.now().timestamp() * 1000) - 24 * 60 * 60 * 1000
    if not end_time:
        end_time = int(datetime.now().timestamp() * 1000)

    loop_uri='/pid_zd/0b521c82a96d4107a564e4c2678bdeca'
    # 根据loop_uri查询表名和测点列表
    table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)

    # 使用环境变量中的数据库名
    db = get_default_database()

    # 使用新的查询方法
    history_data: List[Dict] = process_query_tsdb_data_interpolated(
        db=db,
        table_name=table,
        required_fields=required_fields,
        start_time=start_time,
        end_time=end_time,
        is_filter=False #是否过滤只获取最新一组pid控制的历史值
    )

    if not history_data:
        print("未获取到历史数")
        return []
    print("获取到历史数据："+len(history_data))
    return history_data