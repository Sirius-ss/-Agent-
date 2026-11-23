import httpx2
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from typesafe_sdk import AsyncTypeSafeClient

from atguigu.common.settings import get_settings


def get_llm_client():
    setting = get_settings()
    enable_thinking = 'enabled' if setting.llm_thinking_mode == "True" else "disabled"

    # llm基础参数
    model_kwargs = {
        "model": setting.llm_model,
        "api_key": setting.llm_api_key,
        "base_url": setting.llm_base_url,
        "timeout": setting.llm_timeout_seconds
    }

    if setting.llm_provider == "deepseek":
        return ChatDeepSeek(
            **model_kwargs,
            extra_body={
                "thinking": {"type": enable_thinking}
            }
        )

    return ChatOpenAI(
        **model_kwargs,
        use_responses_api=False
    )


def get_jev_client() -> AsyncTypeSafeClient:
    """获取TypeSafe JEV模型客户端实例"""
    setting = get_settings()

    proxy = setting.typesafe_proxy.strip()
    http_client = (
        httpx2.AsyncClient(proxy=proxy, trust_env=False, timeout=httpx2.Timeout(20, connect=8))
        if proxy else None
    )

    return AsyncTypeSafeClient(
        api_key=setting.typesafe_api_key,
        base_url=setting.typesafe_base_url,
        model=setting.typesafe_model,
        http_client=http_client,
    )

