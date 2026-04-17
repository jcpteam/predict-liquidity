"""
数据库操作工具类
提供通用的数据插入和更新功能
"""
import pymysql
from typing import List, Dict, Any
from database import DB_HOST, DB_PORT, DB_USER, DB_PASSWD, DB_NAME


def batch_insert(table_name: str, data_list: List[Dict[str, Any]], 
                 unique_key: str = 'market_id', update_fields: List[str] = None):
    """
    批量插入数据到指定表，支持幂等更新
    
    Args:
        table_name: 表名
        data_list: 数据列表，每个元素是字典
        unique_key: 唯一键字段名（用于 ON DUPLICATE KEY UPDATE 判断）
        update_fields: 需要更新的字段列表，默认为除 id 和 unique_key 外的所有字段
    
    Returns:
        插入的行数
    """
    if not data_list:
        print(f"[db] No data to insert into {table_name}")
        return 0
    
    print(f"\n[db] Connecting to {DB_HOST}...")
    conn = pymysql.connect(
        host=DB_HOST, 
        port=int(DB_PORT), 
        user=DB_USER, 
        password=DB_PASSWD,
        database=DB_NAME, 
        charset='utf8mb4',
    )
    cur = conn.cursor()
    
    try:
        # 获取第一条数据的字段
        first_row = data_list[0]
        fields = list(first_row.keys())
        
        # 构建 INSERT 语句
        placeholders = ', '.join(['%s'] * len(fields))
        columns = ', '.join(fields)
        
        # 确定需要更新的字段
        if update_fields is None:
            # 默认排除 id 和唯一键
            exclude_fields = {'id', unique_key}
            update_fields = [f for f in fields if f not in exclude_fields]
        
        # 构建 ON DUPLICATE KEY UPDATE 子句
        update_clause = ', '.join([f"{field}=VALUES({field})" for field in update_fields])
        
        sql = f"""
            INSERT INTO {table_name} ({columns})
            VALUES ({placeholders})
            ON DUPLICATE KEY UPDATE {update_clause}
        """
        
        # 准备数据行
        rows = [tuple(row[field] for field in fields) for row in data_list]
        
        # 批量插入
        cur.executemany(sql, rows)
        conn.commit()
        
        print(f"[db] Inserted {len(rows)} rows into {table_name}")
        return len(rows)
        
    except Exception as e:
        conn.rollback()
        print(f"[db] Error inserting into {table_name}: {e}")
        raise
    finally:
        cur.close()
        conn.close()
        print("[db] Connection closed")
