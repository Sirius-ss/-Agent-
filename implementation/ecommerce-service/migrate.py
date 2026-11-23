from pathlib import Path
from ecommerce_service.database import Base, engine, SessionLocal
from ecommerce_service.seed import seed_demo_data
from ecommerce_service.appliance_seed import seed_appliances

if __name__ == "__main__":
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        conn.exec_driver_sql((Path(__file__).parent/"migrations/001_appliance.sql").read_text(encoding="utf8"))
    with SessionLocal() as db:
        seed_demo_data(db)
        seed_appliances(db)
