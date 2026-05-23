import os

import redis.asyncio as redis
from dotenv import load_dotenv

try:
	from upstash_redis.asyncio import Redis as UpstashRedis
except ImportError:  # pragma: no cover - optional dependency for local builds.
	UpstashRedis = None

load_dotenv()


def _build_redis_client():
	redis_url = os.getenv("REDIS_URL", "").strip()
	if redis_url:
		print(f"Connecting to Redis at: {redis_url}")
		return redis.from_url(redis_url, decode_responses=True)

	rest_url = os.getenv("UPSTASH_REDIS_REST_URL", "").strip()
	rest_token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
	if rest_url and rest_token:
		if UpstashRedis is None:
			raise RuntimeError("upstash-redis is not installed. Add it to the image build.")
		print(f"Connecting to Upstash Redis REST at: {rest_url}")
		return UpstashRedis(url=rest_url, token=rest_token, allow_telemetry=False)

	raise RuntimeError(
		"Set REDIS_URL or UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN in AccuEntry_Verify/.env"
	)


redis_client = _build_redis_client()
