import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.engine import URL

# Find .env in the parent directory of app (backend/). A persistent external
# secret store is loaded first, so values in the local .env cannot overwrite
# secrets injected by a deployment/bootstrap provider.
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
secret_store_path = Path(
    os.getenv("CLOUD_SECRET_STORE_PATH")
    or (Path.home() / ".smart-campus-cloud" / "production-secrets.env")
).expanduser()
load_dotenv(dotenv_path=secret_store_path, override=False)
load_dotenv(dotenv_path=dotenv_path, override=False)

class Settings:
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "3306")
    DB_USER: str = os.getenv("DB_USER", "smart_campus_app")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_NAME: str = os.getenv("DB_NAME", "biometric_rag_db")
    
    @property
    def DATABASE_URL(self) -> URL:
        return URL.create(
            "mysql+mysqlconnector",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=int(self.DB_PORT),
            database=self.DB_NAME,
        )

    # There is intentionally no fallback for credentials.  The application can
    # be imported for tooling/tests, but startup validates these values before
    # accepting traffic.
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))
    APP_ENV: str = os.getenv("APP_ENV", "development").lower()
    DASHBOARD_ORIGINS: tuple[str, ...] = tuple(
        origin.strip() for origin in os.getenv("DASHBOARD_ORIGINS", "http://127.0.0.1:5173").split(",") if origin.strip()
    )
    TRUSTED_PROXY_IPS: tuple[str, ...] = tuple(
        value.strip() for value in os.getenv("TRUSTED_PROXY_IPS", "").split(",") if value.strip()
    )
    DEVICE_CREDENTIAL_KEY: str = os.getenv("DEVICE_CREDENTIAL_KEY", "")
    RATE_LIMIT_REDIS_URL: str = os.getenv("RATE_LIMIT_REDIS_URL", "")
    PRIVATE_STORAGE_ROOT: Path = Path(
        os.getenv("PRIVATE_STORAGE_ROOT", str(Path(__file__).resolve().parents[4] / "runtime-data" / "private"))
    ).expanduser().resolve()
    MAX_DOCUMENT_BYTES: int = int(os.getenv("MAX_DOCUMENT_BYTES", str(25 * 1024 * 1024)))
    MAX_BIOMETRIC_BYTES: int = int(os.getenv("MAX_BIOMETRIC_BYTES", str(10 * 1024 * 1024)))
    MAX_SURVEILLANCE_BYTES: int = int(os.getenv("MAX_SURVEILLANCE_BYTES", str(10 * 1024 * 1024)))
    MAX_AI_CONCURRENCY: int = int(os.getenv("MAX_AI_CONCURRENCY", "8"))
    CSRF_COOKIE_NAME: str = "csrf_token"
    ACCESS_COOKIE_NAME: str = "access_token"
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "true").lower() in {"1", "true", "yes", "on"}

    def validate_security(self) -> None:
        secret = self.JWT_SECRET.strip()
        weak_values = {"", "secret", "change-me", "changeme", "password", "jwt_secret"}
        if secret.lower() in weak_values or len(secret) < 32:
            raise RuntimeError("JWT_SECRET must be provided externally and contain at least 32 non-default characters")
        if self.JWT_ALGORITHM not in {"HS256", "HS384", "HS512"}:
            raise RuntimeError("Only HMAC JWT algorithms configured by the deployment are supported")
        if self.APP_ENV == "production" and not self.DEVICE_CREDENTIAL_KEY:
            raise RuntimeError("DEVICE_CREDENTIAL_KEY must be provided by production secret storage")
        if self.APP_ENV == "production" and not self.RATE_LIMIT_REDIS_URL:
            raise RuntimeError("RATE_LIMIT_REDIS_URL must be provided in production")
        if self.APP_ENV == "production" and (self.DB_USER.strip().lower() == "root" or not self.DB_PASSWORD.strip()):
            raise RuntimeError("Production requires a least-privilege database account with a password")
        if self.APP_ENV == "production" and not self.COOKIE_SECURE:
            raise RuntimeError("COOKIE_SECURE must be enabled in production")
        self.PRIVATE_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

settings = Settings()


def get_development_device_credential_key() -> str:
    """Return a persistent local-only device key for development.

    Production never uses this fallback. It must receive
    DEVICE_CREDENTIAL_KEY from deployment secret storage.
    """
    if settings.DEVICE_CREDENTIAL_KEY:
        return settings.DEVICE_CREDENTIAL_KEY
    if settings.APP_ENV != "development":
        return ""

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return ""

    configured_path = os.getenv("DEVICE_CREDENTIAL_KEY_PATH")
    key_path = Path(configured_path).expanduser() if configured_path else Path.home() / ".smart-campus-cloud" / "device_credential.key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.is_file():
        key = key_path.read_text(encoding="utf-8").strip()
        try:
            Fernet(key.encode())
        except Exception as exc:
            raise RuntimeError(f"Invalid development device credential key: {key_path}") from exc
    else:
        key = Fernet.generate_key().decode()
        temporary_path = key_path.with_suffix(key_path.suffix + ".tmp")
        temporary_path.write_text(key + "\n", encoding="utf-8")
        os.replace(temporary_path, key_path)
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
    settings.DEVICE_CREDENTIAL_KEY = key
    return key
