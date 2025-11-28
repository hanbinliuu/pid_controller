#!/usr/bin/env python3
"""
回路路径映射表单元测试
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from sqlmodel import Session, create_engine, SQLModel
from sqlmodel import Session as SQLModelSession

# 导入模型
from api.bean.loop_path_mapping import LoopPathMapping
from api.dao.loop_path_mapping_dao import LoopPathMappingDAO
from api.services.loop_path_mapping_service import LoopPathMappingService


def test_loop_path_mapping():
    """测试回路路径映射的CRUD操作"""
    
    # 创建内存SQLite数据库用于测试
    sqlite_url = "sqlite:///:memory:"
    engine = create_engine(
        sqlite_url,
        connect_args={"check_same_thread": False},
        echo=True
    )
    
    # 创建所有表
    SQLModel.metadata.create_all(engine)
    
    with SQLModelSession(engine) as db:
        print("\n=== 测试创建映射 ===")
        # 创建映射
        mapping_data = {
            "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
            "loop_path": "/设备/反应器/温度控制回路",
            "loop_name": "FIC101A流量控制回路",
            "pv_field": "FIC101A_PV",
            "sv_field": "FIC101A_SV",
            "mv_field": "FIC101A_MV",
            "op_field": "FIC101A_OP",
            "auto_status_field": "FIC101A_AUTO",
            "description": "主要流量控制回路"
        }
        
        mapping = LoopPathMappingDAO.create(db, mapping_data)
        print(f"✓ 创建成功: {mapping}")
        print(f"  - ID: {mapping.id}")
        print(f"  - loop_uri: {mapping.loop_uri}")
        print(f"  - loop_path: {mapping.loop_path}")
        print(f"  - loop_name: {mapping.loop_name}")
        
        print("\n=== 测试根据URI查询 ===")
        # 根据URI查询
        found = LoopPathMappingDAO.get_by_loop_uri(db, "/pid_zd/0b521c82a96d4107a564e4c2678bdeca")
        if found:
            print(f"✓ 查询成功: {found.loop_name}")
        else:
            print("✗ 查询失败")
        
        print("\n=== 测试根据路径查询 ===")
        # 根据路径查询
        found = LoopPathMappingDAO.get_by_loop_path(db, "/设备/反应器/温度控制回路")
        if found:
            print(f"✓ 查询成功: {found.loop_uri}")
        else:
            print("✗ 查询失败")
        
        print("\n=== 测试更新映射 ===")
        # 更新映射
        update_data = {
            "loop_name": "FIC101A流量控制回路(已优化)",
            "pv_field": "FIC101A_PV_NEW"
        }
        updated = LoopPathMappingDAO.update_by_loop_uri(
            db,
            "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
            update_data
        )
        if updated:
            print(f"✓ 更新成功: {updated.loop_name}")
        else:
            print("✗ 更新失败")
        
        print("\n=== 测试获取URI到路径映射字典 ===")
        # 创建第二条记录用于测试字典功能
        mapping_data2 = {
            "loop_uri": "/pid_zd/xyz789",
            "loop_path": "/设备/冷凝器/温度控制回路",
            "loop_name": "TIC202温度控制",
            "is_active": True
        }
        mapping2 = LoopPathMappingDAO.create(db, mapping_data2)
        
        # 获取URI到路径的映射字典
        uri_to_path = LoopPathMappingDAO.get_uri_to_path_map(db)
        print(f"✓ URI到路径映射:")
        for uri, path in uri_to_path.items():
            print(f"  - {uri} => {path}")
        
        print("\n=== 测试获取路径到URI映射字典 ===")
        # 获取路径到URI的映射字典
        path_to_uri = LoopPathMappingDAO.get_path_to_uri_map(db)
        print(f"✓ 路径到URI映射:")
        for path, uri in path_to_uri.items():
            print(f"  - {path} => {uri}")
        
        print("\n=== 测试分页查询 ===")
        # 分页查询
        result = LoopPathMappingDAO.query_list(
            db,
            page_no=1,
            page_size=10
        )
        print(f"✓ 查询结果:")
        print(f"  - 总数: {result['pagination']['total']}")
        print(f"  - 当前页: {result['pagination']['pageNo']}")
        print(f"  - 总页数: {result['pagination']['pages']}")
        print(f"  - 记录数: {len(result['mappings'])}")
        
        print("\n=== 测试删除映射 ===")
        # 删除映射
        success = LoopPathMappingDAO.delete_by_loop_uri(
            db,
            "/pid_zd/xyz789"
        )
        if success:
            print(f"✓ 删除成功")
        else:
            print("✗ 删除失败")
        
        # 验证删除
        result = LoopPathMappingDAO.query_list(db)
        print(f"  - 删除后总数: {result['pagination']['total']}")
        
        print("\n=== 所有测试完成 ===")


if __name__ == "__main__":
    test_loop_path_mapping()
