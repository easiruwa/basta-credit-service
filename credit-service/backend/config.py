from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "credit"
    redis_url: str = "redis://localhost:6379/0"

settings = Settings()