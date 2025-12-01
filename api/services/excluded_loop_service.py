#!/usr/bin/env python3
"""
业务逻辑层 - 条件剔除回路服务
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlmodel import Session, select

from api.dao.excluded_loop_dao import ExcludedLoopDAO
from api.bean.excluded_loop import ExcludedLoop
from api.bean.loop_info import LoopInfo
from api.middleware.exceptions import ValidationException

logger = logging.getLogger(__name__)


class ExcludedLoopService:
    """条件剔除回路业务逻辑服务"""
    
    @staticmethod
    def _validate_uri_exists(db: Session, uri: str) -> bool:
        """
        校验URI是否在loop_info表中存在
        
        Args:
            db: 数据库会话
            uri: 回路URI
        
        Returns:
            bool: URI是否存在
        
        Raises:
            ValidationException: 如果URI不存在
        """
        try:
            statement = select(LoopInfo).where(LoopInfo.loop_uri == uri)
            loop_info = db.exec(statement).first()
            
            if not loop_info:
                raise ValidationException(
                    message=f"回路URI不存在: {uri}",
                    data={"uri": uri}
                )
            
            return True
            
        except ValidationException:
            raise
        except Exception as e:
            logger.error(f"校验URI失败: {str(e)}")
            raise ValidationException(
                message=f"校验URI失败: {str(e)}",
                data={"uri": uri}
            )
    
    @staticmethod
    def add_excluded(
        db: Session,
        uri: str,
        reason: Optional[str] = None
    ) -> ExcludedLoop:
        """
        添加条件剔除记录（支持自动更新）
        如果URI已存在，则更新记录；否则创建新记录
        
        Args:
            db: 数据库会话
            uri: 回路/装置URI
            reason: 剔除原因
        
        Returns:
            ExcludedLoop: 创建或更新的剔除对象
        
        Raises:
            ValidationException: 如果URI不存在
        """
        try:
            # 校验URI是否存在
            ExcludedLoopService._validate_uri_exists(db, uri)
            
            excluded_data = {}
            
            if reason is not None:
                excluded_data["reason"] = reason
            
            return ExcludedLoopDAO.upsert_by_uri(db, uri, excluded_data)
            
        except ValidationException:
            raise
        except Exception as e:
            logger.error(f"添加条件剔除记录失败: {str(e)}")
            raise
    
    @staticmethod
    def remove_excluded(db: Session, uri: str) -> bool:
        """
        移除条件剔除（直接删除记录）
        
        Args:
            db: 数据库会话
            uri: 回路/装置URI
        
        Returns:
            bool: 是否删除成功
        """
        try:
            excluded = ExcludedLoopDAO.get_by_uri(db, uri)
            if excluded:
                return ExcludedLoopDAO.delete(db, excluded.id)
            return False
            
        except Exception as e:
            logger.error(f"移除条件剔除失败: {str(e)}")
            raise
    
    @staticmethod
    def get_excluded_by_id(db: Session, excluded_id: int) -> Optional[ExcludedLoop]:
        """
        根据ID获取剔除记录
        
        Args:
            db: 数据库会话
            excluded_id: 剔除记录ID
        
        Returns:
            Optional[ExcludedLoop]: 剔除对象
        """
        return ExcludedLoopDAO.get_by_id(db, excluded_id)
    
    @staticmethod
    def get_excluded_by_uri(db: Session, uri: str) -> Optional[ExcludedLoop]:
        """
        根据URI获取剔除记录
        
        Args:
            db: 数据库会话
            uri: 回路/装置URI
        
        Returns:
            Optional[ExcludedLoop]: 剔除对象
        """
        return ExcludedLoopDAO.get_by_uri(db, uri)
    
    @staticmethod
    def is_excluded(db: Session, uri: str) -> bool:
        """
        检查URI是否被条件剔除
        
        Args:
            db: 数据库会话
            uri: 回路/装置URI
        
        Returns:
            bool: 是否被剔除
        """
        excluded = ExcludedLoopDAO.get_by_uri(db, uri)
        return excluded is not None
    
    @staticmethod
    def list_excluded(
        db: Session,
        loop_name: Optional[str] = None,
        device_uri: Optional[str] = None,
        uri: Optional[str] = None,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        分页查询剔除记录列表
        
        Args:
            db: 数据库会话
            loop_name: 回路名称筛选
            device_uri: 装置URI筛选
            uri: 回路URI筛选
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含剔除列表和分页信息
        """
        return ExcludedLoopDAO.query_list(
            db,
            loop_name=loop_name,
            device_uri=device_uri,
            uri=uri,
            page_no=page_no,
            page_size=page_size
        )
    
    @staticmethod
    def get_all_excluded_uris(
        db: Session,
        loop_name: Optional[str] = None,
        device_uri: Optional[str] = None,
        uri: Optional[str] = None
    ) -> List[str]:
        """
        获取所有剔除回路URI列表（支持筛选）
        
        Args:
            db: 数据库会话
            loop_name: 回路名称筛选
            device_uri: 装置URI筛选
            uri: 回路URI筛选
        
        Returns:
            List[str]: URI列表
        """
        return ExcludedLoopDAO.get_all_uris(db, loop_name, device_uri, uri)
    
    @staticmethod
    def update_excluded(
        db: Session,
        excluded_id: int,
        uri: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Optional[ExcludedLoop]:
        """
        更新剔除记录
        
        Args:
            db: 数据库会话
            excluded_id: 剔除记录ID
            uri: 新的URI
            reason: 新的剔除原因
        
        Returns:
            Optional[ExcludedLoop]: 更新后的剔除对象
        """
        try:
            update_data = {}
            
            if uri is not None:
                update_data["uri"] = uri
            if reason is not None:
                update_data["reason"] = reason
            
            return ExcludedLoopDAO.update(db, excluded_id, update_data)
            
        except Exception as e:
            logger.error(f"更新条件剔除记录失败: {str(e)}")
            raise
    
    @staticmethod
    def delete_excluded(db: Session, excluded_id: int) -> bool:
        """
        删除剔除记录
        
        Args:
            db: 数据库会话
            excluded_id: 剔除记录ID
        
        Returns:
            bool: 是否删除成功
        """
        return ExcludedLoopDAO.delete(db, excluded_id)
    
    @staticmethod
    def batch_add_excluded(
        db: Session,
        uris: List[str],
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        批量添加条件剔除
        
        Args:
            db: 数据库会话
            uris: URI列表
            reason: 剔除原因
        
        Returns:
            Dict: 批量操作结果
        """
        try:
            success_count = 0
            failed_count = 0
            failed_uris = []
            
            for uri in uris:
                try:
                    ExcludedLoopService.add_excluded(
                        db, uri, reason
                    )
                    success_count += 1
                except Exception as e:
                    failed_count += 1
                    failed_uris.append({
                        "uri": uri,
                        "error": str(e)
                    })
                    logger.warning(f"批量添加剔除失败 - URI: {uri}, 错误: {str(e)}")
            
            result = {
                "total": len(uris),
                "success": success_count,
                "failed": failed_count,
                "failed_details": failed_uris
            }
            
            logger.info(f"批量添加条件剔除完成 - 总数: {len(uris)}, 成功: {success_count}, 失败: {failed_count}")
            return result
            
        except Exception as e:
            logger.error(f"批量添加条件剔除失败: {str(e)}")
            raise
    
    @staticmethod
    def batch_remove_excluded(db: Session, uris: List[str]) -> Dict[str, Any]:
        """
        批量移除条件剔除
        
        Args:
            db: 数据库会话
            uris: URI列表
        
        Returns:
            Dict: 批量操作结果
        """
        try:
            success_count = 0
            failed_count = 0
            failed_uris = []
            
            for uri in uris:
                try:
                    result = ExcludedLoopService.remove_excluded(db, uri)
                    if result:
                        success_count += 1
                    else:
                        failed_count += 1
                        failed_uris.append({
                            "uri": uri,
                            "error": "记录不存在"
                        })
                except Exception as e:
                    failed_count += 1
                    failed_uris.append({
                        "uri": uri,
                        "error": str(e)
                    })
                    logger.warning(f"批量移除剔除失败 - URI: {uri}, 错误: {str(e)}")
            
            result = {
                "total": len(uris),
                "success": success_count,
                "failed": failed_count,
                "failed_details": failed_uris
            }
            
            logger.info(f"批量移除条件剔除完成 - 总数: {len(uris)}, 成功: {success_count}, 失败: {failed_count}")
            return result
            
        except Exception as e:
            logger.error(f"批量移除条件剔除失败: {str(e)}")
            raise
