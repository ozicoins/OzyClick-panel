from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from redis.asyncio import Redis, ConnectionPool
from config import settings


# Lokal geliştirme modu: DATABASE_URL sqlite ise altyapısız çalış (Postgres gerekmez).
_IS_SQLITE = settings.database_url.startswith("sqlite")

if _IS_SQLITE:
    engine = create_async_engine(settings.database_url, echo=False)
else:
    engine = create_async_engine(
        settings.database_url,
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
    )

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
async_session_factory = AsyncSessionLocal


class Base(DeclarativeBase):
    pass


_redis_pool: ConnectionPool | None = None
_redis_client: Redis | None = None


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    await engine.dispose()


async def get_redis() -> Redis:
    global _redis_pool, _redis_client
    if _redis_client is None:
        # Lokal mod: REDIS_URL "fake"/"memory" ile başlıyorsa gerçek Redis'e gerek yok.
        if settings.redis_url.startswith(("fake", "memory")):
            import fakeredis.aioredis
            _redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        else:
            _redis_pool = ConnectionPool.from_url(
                settings.redis_url,
                max_connections=100,
                decode_responses=True,
            )
            _redis_client = Redis(connection_pool=_redis_pool)
    return _redis_client


async def close_redis():
    global _redis_client, _redis_pool
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
    if _redis_pool:
        await _redis_pool.aclose()
        _redis_pool = None


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
