#!/usr/bin/env python3
"""
Railway PostgreSQL 数据库初始化脚本
在 Railway 环境中执行此脚本来创建会话上下文表
"""
import os
import sys
from dotenv import load_dotenv
import psycopg2
from psycopg2 import sql
from pathlib import Path

# 加载环境变量
load_dotenv()

def get_database_url():
    """获取数据库连接字符串"""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ ERROR: DATABASE_URL environment variable not found!")
        print("Please ensure you have Railway PostgreSQL service configured.")
        return None
    return db_url

def execute_init_script(db_url: str) -> bool:
    """执行初始化脚本"""
    try:
        print(f"[DB-INIT] Connecting to Railway PostgreSQL...")
        print(f"[DB-INIT] Connection string: {db_url[:50]}...")
        
        # 连接到数据库
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        print("[DB-INIT] ✅ Connected to PostgreSQL")
        
        # 读取并执行初始化脚本
        script_path = Path(__file__).parent / "migrations" / "init_conversation_tables.sql"
        
        if not script_path.exists():
            print(f"❌ ERROR: Script not found at {script_path}")
            return False
        
        print(f"[DB-INIT] Reading initialization script from {script_path}")
        
        with open(script_path, 'r', encoding='utf-8') as f:
            sql_script = f.read()
        
        # 执行脚本
        print("[DB-INIT] Executing SQL initialization script...")
        cursor.execute(sql_script)
        conn.commit()
        
        print("[DB-INIT] ✅ Initialization script executed successfully")
        
        # 验证表是否创建成功
        print("[DB-INIT] Verifying table creation...")
        
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('conversation_contexts', 'drawing_history')
        """)
        
        tables = cursor.fetchall()
        
        if len(tables) == 2:
            print("[DB-INIT] ✅ Both tables created successfully:")
            for table in tables:
                print(f"  - {table[0]}")
        else:
            print(f"⚠️  WARNING: Expected 2 tables, found {len(tables)}")
            for table in tables:
                print(f"  - {table[0]}")
        
        # 显示表的结构
        print("\n[DB-INIT] Table structure for 'conversation_contexts':")
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'conversation_contexts'
            ORDER BY ordinal_position
        """)
        
        columns = cursor.fetchall()
        for col_name, col_type, is_nullable in columns:
            nullable = "NULL" if is_nullable == 'YES' else "NOT NULL"
            print(f"  - {col_name:30} {col_type:20} {nullable}")
        
        print("\n[DB-INIT] Indexes created:")
        cursor.execute("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename IN ('conversation_contexts', 'drawing_history')
        """)
        
        indexes = cursor.fetchall()
        for idx in indexes:
            print(f"  - {idx[0]}")
        
        print("\n[DB-INIT] Functions created:")
        cursor.execute("""
            SELECT routine_name 
            FROM information_schema.routines 
            WHERE routine_schema = 'public'
            AND routine_name IN ('update_conversation_context_timestamp', 'cleanup_expired_contexts')
        """)
        
        functions = cursor.fetchall()
        for func in functions:
            print(f"  - {func[0]}")
        
        cursor.close()
        conn.close()
        
        print("\n" + "="*60)
        print("✅ DATABASE INITIALIZATION COMPLETED SUCCESSFULLY!")
        print("="*60)
        print("\nYou can now:")
        print("1. Deploy the new Python code with the conversation context modules")
        print("2. The application will automatically use these tables")
        print("3. Multi-turn conversation support is now ready!")
        
        return True
        
    except psycopg2.OperationalError as e:
        print(f"❌ ERROR: Cannot connect to database")
        print(f"   {e}")
        print("\nMake sure:")
        print("  - You have a PostgreSQL service in Railway")
        print("  - The DATABASE_URL environment variable is set")
        print("  - You're running this in the Railway environment or with proper env vars")
        return False
    except psycopg2.ProgrammingError as e:
        print(f"❌ ERROR: SQL syntax error")
        print(f"   {e}")
        return False
    except Exception as e:
        print(f"❌ ERROR: Unexpected error")
        print(f"   {e}")
        return False

def main():
    """主函数"""
    print("="*60)
    print("Railway PostgreSQL Database Initialization")
    print("="*60)
    print()
    
    db_url = get_database_url()
    if not db_url:
        sys.exit(1)
    
    success = execute_init_script(db_url)
    
    if success:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()

