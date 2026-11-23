from datetime import date
from sqlalchemy import select, text
from ecommerce_service.models import Logistics, Product, Order, OrderItem

def seed_appliances(db):
    for code, name, months in [("W-DEMO","DEMO 洗衣机",12),("A-DEMO","DEMO 空调",24)]:
        if not db.get(Product, code):
            db.add(Product(id=code,name=name,category="DEMO 家电",price=1000,stock=4,
                           description="DEMO 售后演示",specs={"型号":code}))
            db.flush()
        db.execute(text("""INSERT INTO appliance_models VALUES(CAST(:code AS text),CAST(:code AS text),:name,:months,true)
                        ON CONFLICT(model_code) DO NOTHING"""),dict(code=code,name=name,months=months))
    for oid,uid,code,count in [("DEMO-W1","user_001","W-DEMO",2),("DEMO-A1","user_001","A-DEMO",1),
                                ("DEMO-W2","user_002","W-DEMO",1)]:
        order=db.get(Order,oid)
        if not order:
            order=Order(id=oid,user_id=uid,status="completed",total_amount=count*1000,address="DEMO 地址")
            order.items=[OrderItem(product_id=code,product_name=db.get(Product,code).name,quantity=count,unit_price=1000)]
            db.add(order)
            db.flush()
        item, = order.items
        item.product_name=db.get(Product,code).name
        for unit in range(1,count+1):
            identifier=f"{oid}-{unit}"
            db.execute(text("""INSERT INTO appliances VALUES(:id,:item,:unit,:serial,:signed)
                               ON CONFLICT(order_item_id,unit_no) DO NOTHING"""),
                       dict(id=identifier,item=item.id,unit=unit,serial=identifier,
                            signed=None if unit==2 else date(2025,6,15)))
        units=db.scalars(text("SELECT unit_no FROM appliances WHERE order_item_id=:item ORDER BY unit_no"),dict(item=item.id)).all()
        if units!=list(range(1,item.quantity+1)):
            raise ValueError("DEMO 订单数量与设备不符")
    for code, name, price, specs in (
        ("W-DEMO-PLUS", "DEMO 大容量洗衣机", 1599, {"型号": "W-DEMO-PLUS", "容量": "12 kg"}),
        ("A-DEMO-PRO", "DEMO 变频空调", 2199, {"型号": "A-DEMO-PRO", "规格": "1.5 匹"}),
    ):
        if not db.get(Product,code):
            db.add(Product(id=code, name=name, category="DEMO 家电", price=price,
                           stock=4, description="DEMO 商城与配送样例", specs=specs))
    db.flush()
    seed_order_scenarios(db)
    db.commit()

def seed_order_scenarios(db):
    """Replace the original demo catalog while preserving order references and workflow states."""
    scenarios = (
        ("ORDER_001", "user_001", "W-DEMO-PLUS", "pending_shipment"),
        ("ORDER_002", "user_001", "A-DEMO-PRO", "shipped"),
        ("ORDER_003", "user_001", "W-DEMO", "completed"),
        ("ORDER_004", "user_002", "A-DEMO", "paid"),
    )
    legacy_ids = {f"PRODUCT_{number:03}" for number in range(1, 6)}
    for order_id, user_id, model_code, initial_status in scenarios:
        product = db.get(Product, model_code)
        order = db.get(Order, order_id)
        if order is None:
            order = Order(id=order_id, user_id=user_id, status=initial_status,
                          address="DEMO 配送地址", total_amount=product.price)
            order.items = [OrderItem(product_id=model_code, product_name=product.name,
                                     quantity=1, unit_price=product.price)]
            db.add(order)
        else:
            prior_model = {"ORDER_001": "W-DEMO", "ORDER_002": "A-DEMO"}.get(order_id)
            legacy_items = [item for item in order.items if item.product_id in legacy_ids or item.product_id == prior_model]
            if not legacy_items:
                continue
            for item in legacy_items:
                item.product_id = model_code
                item.product_name = product.name
                item.unit_price = product.price
            order.total_amount = sum(item.quantity * item.unit_price for item in order.items)
        if initial_status in {"shipped", "completed"}:
            delivered = initial_status == "completed"
            event = "DEMO 家电已签收" if delivered else "DEMO 空调已到达上海浦东分拣中心"
            shipment = order.logistics or Logistics()
            shipment.company = "DEMO 家电配送"
            shipment.tracking_number = f"DEMO-TRACK-{order_id[-3:]}"
            shipment.status = "delivered" if delivered else "in_transit"
            shipment.latest_event = event
            shipment.events = [{"time": "2026-11-21 10:00", "description": event}]
            order.logistics = shipment
    db.flush()
    for product_id in legacy_ids:
        product = db.get(Product, product_id)
        if product is not None and not db.scalar(select(OrderItem.id).where(OrderItem.product_id == product_id).limit(1)):
            db.delete(product)
