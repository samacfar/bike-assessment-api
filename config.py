from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = "https://trgqgqbjcczowlxbhfqx.supabase.co"
    supabase_service_role_key: str
    anthropic_api_key: str

    class Config:
        env_file = ".env"


def get_settings() -> Settings:
    return Settings()
