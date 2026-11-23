from redis.asyncio import Redis
from atguigu.common.settings import get_settings

redis_client = Redis.from_url(get_settings().redis_url,decode_responses=True, protocol=2)
