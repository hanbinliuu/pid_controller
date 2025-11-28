#!/usr/bin/env python3
"""
数据库配置和会话管理 - 使用SQLModel
SQLModel = SQLAlchemy + Pydantic
"""
import logging
from typing import Generator
from sqlmodel import create_engine, Session, SQLModel
from sqlalchemy import event, pool
from core.config import Config

logger = logging.getLogger(__name__)

# 从配置获取数据库URL
DATABASE_URL = Config.DATABASE_URL

# 创建数据库引擎 - SQLModel方式
connect_args = {}
if DATABASE_URL.startswith('sqlite'):
    # SQLite特定配置
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=Config.SQL_ECHO,
    pool_pre_ping=True,
    pool_size=Config.DB_POOL_SIZE,
    max_overflow=Config.DB_MAX_OVERFLOW,
    pool_recycle=3600,
    poolclass=pool.QueuePool
)

# 监听连接事件
@event.listens_for(engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    logger.debug(f"数据库连接建立: {connection_record}")

@event.listens_for(engine, "close")
def receive_close(dbapi_conn, connection_record):
    logger.debug(f"数据库连接关闭: {connection_record}")




def get_db() -> Generator[Session, None, None]:
    """
    获取数据库会话的依赖函数 - SQLModel方式
    
    用法：
        @router.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.exec(select(Item)).all()
    """
    with Session(engine) as session:
        yield session


def init_database():
    """
    初始化数据库 - SQLModel方式
    创建所有SQLModel模型定义的表
    """
    try:
        # 导入所有模型以确保它们被注册
        from api.bean import tuning_record
        from api.bean import loop_evaluation
        from api.bean import loop_path_mapping

        # 创建所有表
        SQLModel.metadata.create_all(engine)
        logger.info(f"数据库初始化成功: {DATABASE_URL}")
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}")
        raise