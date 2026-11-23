from sqlalchemy import select
from sqlalchemy.orm import Session

from ecommerce_service.models import User


def seed_demo_data(db: Session) -> None:
    if db.scalar(select(User.id).limit(1)):
        return
    users = [
        User(id="user_001", name="李明", membership="金牌会员"),
        User(id="user_002", name="王芳", membership="普通会员"),
        User(id="agent_001", name="客服小周", membership="员工"),
        User(id="admin_001", name="系统管理员", membership="员工"),
    ]
    db.add_all(users)
    db.commit()
