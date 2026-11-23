from pathlib import Path
from sqlalchemy import create_engine
from atguigu.app.models.models import Base
from atguigu.common.settings import get_settings

def main():
    with create_engine(get_settings().database_url).begin() as conn:
        Base.metadata.create_all(conn)
        for migration in sorted((Path(__file__).parent/"migrations").glob("*.sql")):
            conn.exec_driver_sql(migration.read_text())

if __name__=="__main__":
    main()
