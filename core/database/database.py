#!/usr/bin/env python3
"""
数据库配置和会话管理 - 使用SQLModel
SQLModel = SQLAlchemy + Pydantic
"""
import logging
from typing import Generator
from contextlib import contextmanager
from sqlmodel import create_engine, Session, SQLModel
from sqlalchemy import event, pool
from core.config import Config

logger = logging.getLogger(__name__)

# 从配置获取数据库URL
DATABASE_URL = Config.DATABASE_URL
DATABASE_INFO = DATABASE_URL.split('@')[-1]

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
    
    用法（FastAPI依赖注入）：
        @router.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.exec(select(Item)).all()
    """
    with Session(engine) as session:
        yield session


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    获取数据库会话的上下文管理器 - 用于普通Python代码
    
    用法（普通代码）：
        with get_db_session() as db:
            result = db.exec(select(Item)).all()
    
    自动处理会话的开启和关闭，无需手动管理
    """
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_db_session() -> Session:
    """
    创建一个新的数据库会话 - 需要手动管理会话生命周期
    
    用法：
        db = create_db_session()
        try:
            result = db.exec(select(Item)).all()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    
    注意：使用完毕后必须手动调用 db.close()
    推荐使用 get_db_session() 上下文管理器，更安全
    """
    return Session(engine)


def init_database():
    """
    初始化数据库 - SQLModel方式
    创建所有SQLModel模型定义的表
    """
    try:
        # 导入所有模型以确保它们被注册
        from api.bean import tuning_record
        from api.bean import loop_evaluation
        from api.bean import loop_info
        from api.bean import device_evaluation

        from api.pid_data_mgr import file_db_models

        # 创建所有表
        SQLModel.metadata.create_all(engine)
        logger.info(f"数据库初始化成功: {DATABASE_INFO}")
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}")
        raise


# 导出常用接口
__all__ = [
    'engine',
    'get_db',
    'get_db_session',
    'create_db_session',
    'init_database',
    'Session',
    'SQLModel'
]