#!/usr/bin/env python3
"""
业务逻辑层 - 回路信息服务
"""
import logging
from typing import List, Optional, Dict, Any
from sqlmodel import Session

from api.dao.loop_info_dao import LoopInfoDAO
from api.bean.loop_info import LoopInfo

logger = logging.getLogger(__name__)


class LoopInfoService:
    """回路信息业务逻辑服务"""
    
    @staticmethod
    def create_mapping(
        db: Session,
        loop_uri: str,
        loop_path: Optional[str] = None,
        loop_name: Optional[str] = None,
        loop_type: Optional[str] = None,
        pv_field: Optional[str] = None,
        sv_field: Optional[str] = None,
        mv_field: Optional[str] = None,
        auto_status_field: Optional[str] = None,
        pb_field: Optional[str] = None,
        ti_field: Optional[str] = None,
        td_field: Optional[str] = None,
        description: Optional[str] = None
    ) -> LoopInfo:
        """
        创建新的回路映射关系
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
            loop_path: PID相关参数的相对路径
            loop_name: 回路名称
            loop_type: 回路类型
            pv_field: PV字段
            sv_field: SV字段
            mv_field: MV字段
            auto_status_field: 自动状态字段
            pb_field: PB(比例带)字段
            ti_field: TI(积分时间常数)字段
            td_field: TD(微分时间常数)字段
            description: 描述
        
        Returns:
            LoopInfo: 创建的映射对象
        """
        try:
            mapping_data = {
                "loop_uri": loop_uri,
                "loop_path": loop_path,
                "loop_name": loop_name,
                "loop_type": loop_type,
                "pv_field": pv_field,
                "sv_field": sv_field,
                "mv_field": mv_field,
                "auto_status_field": auto_status_field,
                "pb_field": pb_field,
                "ti_field": ti_field,
                "td_field": td_field,
                "description": description,
                "is_active": True
            }
            
            return LoopInfoDAO.create(db, mapping_data)
            
        except Exception as e:
            logger.error(f"创建回路映射关系失败: {str(e)}")
            raise
    
    @staticmethod
    def get_mapping_by_uri(db: Session, loop_uri: str) -> Optional[LoopInfo]:
        """
        根据loop_uri获取映射关系
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
        
        Returns:
            Optional[LoopInfo]: 映射对象
        """
        return LoopInfoDAO.get_by_loop_uri(db, loop_uri)
    
    @staticmethod
    def get_mapping_by_path(db: Session, loop_path: str) -> List[LoopInfo]:
        """
        根据loop_path获取映射关系
        
        Args:
            db: 数据库会话
            loop_path: 回路路径
        
        Returns:
            Optional[LoopInfo]: 映射对象
        """
        return LoopInfoDAO.get_by_loop_path(db, loop_path)
    
    @staticmethod
    def get_all_mappings(db: Session) -> List[LoopInfo]:
        """
        获取所有激活的映射关系
        
        Args:
            db: 数据库会话
        
        Returns:
            List[LoopInfo]: 映射关系列表
        """
        return LoopInfoDAO.get_active_loops(db)
    
    @staticmethod
    def list_mappings(
        db: Session,
        loop_name: Optional[str] = None,
        loop_uri: Optional[str] = None,
        loop_path: Optional[str] = None,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        分页查询映射关系列表
        
        Args:
            db: 数据库会话
            loop_name: 回路名称
            loop_uri: 回路URI
            loop_path: 回路路径
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含映射列表和分页信息
        """
        return LoopInfoDAO.query_list(
            db,
            loop_name=loop_name,
            loop_uri=loop_uri,
            loop_path=loop_path,
            is_active=True,
            page_no=page_no,
            page_size=page_size
        )
    
    @staticmethod
    def update_mapping(
        db: Session,
        loop_uri: str,
        loop_path: Optional[str] = None,
        loop_name: Optional[str] = None,
        loop_type: Optional[str] = None,
        pv_field: Optional[str] = None,
        sv_field: Optional[str] = None,
        mv_field: Optional[str] = None,
        auto_status_field: Optional[str] = None,
        pb_field: Optional[str] = None,
        ti_field: Optional[str] = None,
        td_field: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[LoopInfo]:
        """
        更新映射关系
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI（用于查找要更新的记录）
            loop_path: 新的PID相关参数相对路径
            loop_name: 新的回路名称
            loop_type: 新的回路类型
            pv_field: 新的PV字段
            sv_field: 新的SV字段
            mv_field: 新的MV字段
            auto_status_field: 新的自动状态字段
            pb_field: 新的PB(比例带)字段
            ti_field: 新的TI(积分时间常数)字段
            td_field: 新的TD(微分时间常数)字段
            description: 新的描述
        
        Returns:
            Optional[LoopInfo]: 更新后的映射对象
        """
        try:
            update_data = {}
            if loop_path is not None:
                update_data["loop_path"] = loop_path
            if loop_name is not None:
                update_data["loop_name"] = loop_name
            if loop_type is not None:
                update_data["loop_type"] = loop_type
            if pv_field is not None:
                update_data["pv_field"] = pv_field
            if sv_field is not None:
                update_data["sv_field"] = sv_field
            if mv_field is not None:
                update_data["mv_field"] = mv_field
            if auto_status_field is not None:
                update_data["auto_status_field"] = auto_status_field
            if pb_field is not None:
                update_data["pb_field"] = pb_field
            if ti_field is not None:
                update_data["ti_field"] = ti_field
            if td_field is not None:
                update_data["td_field"] = td_field
            if description is not None:
                update_data["description"] = description
            
            return LoopInfoDAO.update_by_loop_uri(db, loop_uri, update_data)
            
        except Exception as e:
            logger.error(f"更新回路映射关系失败: {str(e)}")
            raise
    
    @staticmethod
    def delete_mapping(db: Session, loop_uri: str) -> bool:
        """
        删除映射关系
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
        
        Returns:
            bool: 是否删除成功
        """
        return LoopInfoDAO.delete_by_loop_uri(db, loop_uri)
    
    @staticmethod
    def get_uri_to_path_map(db: Session) -> Dict[str, str]:
        """
        获取uri到path的映射字典，用于快速查询
        
        Args:
            db: 数据库会话
        
        Returns:
            Dict[str, str]: {loop_uri: loop_path}
        """
        return LoopInfoDAO.get_uri_to_path_map(db)
    
    @staticmethod
    def get_path_to_uri_map(db: Session) -> Dict[str, str]:
        """
        获取path到uri的映射字典，用于快速查询
        
        Args:
            db: 数据库会话
        
        Returns:
            Dict[str, str]: {loop_path: loop_uri}
        """
        return LoopInfoDAO.get_path_to_uri_map(db)
    
    @staticmethod
    def batch_create_mappings(
        db: Session,
        mapping_list: List[Dict[str, Any]]
    ) -> List[LoopInfo]:
        """
        批量创建映射关系
        
        Args:
            db: 数据库会话
            mapping_list: 映射数据列表，每个元素包含loop_uri、loop_path等字段
        
        Returns:
            List[LoopInfo]: 创建的映射对象列表
        """
        try:
            created_mappings = []
            for mapping_data in mapping_list:
                mapping = LoopInfoDAO.create(db, mapping_data)
                created_mappings.append(mapping)
            
            logger.info(f"批量创建回路映射关系成功，共创建 {len(created_mappings)} 条记录")
            return created_mappings
            
        except Exception as e:
            logger.error(f"批量创建回路映射关系失败: {str(e)}")
            raise