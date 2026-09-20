import os
import secrets
from dotenv import load_dotenv

from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

import jwt
import bcrypt
from fastapi import FastAPI, Depends, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select, func, ForeignKey, JSON
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Carrega variáveis do .env
load_dotenv()

# Conexão com o DB
pg_user = os.getenv("DB_USER")
pg_password = os.getenv("DB_PASSWORD")
pg_host = os.getenv("DB_HOST")
pg_port = os.getenv("DB_PORT")
pg_name = os.getenv("DB_NAME")

engine = create_async_engine(
    f"postgresql+asyncpg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_name}",
    echo=True,
)

# ---------- Configuração de autenticação ----------
JWT_SECRET = os.getenv("JWT_SECRET")  # obrigatório: gere com `openssl rand -hex 32`
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 365  # token de longa duração: o app guarda e reusa, sem pedir login de novo

# Chave usada só para criar o primeiro admin de um tenant (bootstrap).
# Depois disso, admins autenticam normalmente via JWT.
ADMIN_SETUP_KEY = os.getenv("ADMIN_SETUP_KEY")

bearer_scheme = HTTPBearer()

limiter = Limiter(key_func=get_remote_address)

# Sessão do SQLAlchemy
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


# Base de models
class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column()
    slug: Mapped[str] = mapped_column(nullable=False, unique=True)
    join_code: Mapped[str] = mapped_column(nullable=False, unique=True)
    max_accounts: Mapped[int] = mapped_column(nullable=False, server_default="5")
    # Lista de {"latitude": .., "longitude": ..} em ordem — a rota fixa do
    # grupo, desenhada no mapa. None/[] quando ainda não foi configurada.
    route_points: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(nullable=False, unique=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    access_code_hash: Mapped[str] = mapped_column(nullable=False)
    is_admin: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    # Perfil complementar — tudo opcional, pode ser preenchido pelo admin no
    # cadastro ou pelo próprio usuário depois, editando o próprio perfil.
    nome: Mapped[str | None] = mapped_column(nullable=True)
    sobrenome: Mapped[str | None] = mapped_column(nullable=True)
    idade: Mapped[int | None] = mapped_column(nullable=True)
    tipo_sanguineo: Mapped[str | None] = mapped_column(nullable=True)
    telefone: Mapped[str | None] = mapped_column(nullable=True)
    contato_emergencia_nome: Mapped[str | None] = mapped_column(nullable=True)
    contato_emergencia_telefone: Mapped[str | None] = mapped_column(nullable=True)
    last_latitude: Mapped[float | None] = mapped_column(nullable=True)
    last_longitude: Mapped[float | None] = mapped_column(nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(nullable=True)
    sos_ativo: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    sos_acionado_em: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Lógica de Startup (ex: carregar modelos, testar conexão com o DB)
    yield
    # Lógica de Shutdown (ex: limpar recursos, encerrar conexões)
    await engine.dispose()


ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

app = FastAPI(
    lifespan=lifespan,
    # Em produção, ninguém de fora precisa ver a documentação interativa.
    docs_url="/docs" if ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if ENVIRONMENT != "production" else None,
    openapi_url="/openapi.json" if ENVIRONMENT != "production" else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: em dev, liberar tudo é aceitável. Em produção, troque "*" pela URL
# real do seu app/painel (ou remova o middleware, já que apps nativos não
# são afetados por CORS de qualquer forma).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_db():
    async with SessionLocal() as db:
        yield db


# ---------- Funções de autenticação ----------

def generate_access_code() -> str:
    """Gera um código numérico de 6 dígitos, fácil de imprimir/digitar."""
    return f"{secrets.randbelow(1_000_000):06d}"


def generate_join_code(length: int = 6) -> str:
    """Gera o código curto do tenant (vira QR code). Evita caracteres
    ambíguos como 0/O e 1/I, já que às vezes é lido/digitado manualmente."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def hash_access_code(code: str) -> str:
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_access_code(code: str, code_hash: str) -> bool:
    return bcrypt.checkpw(code.encode("utf-8"), code_hash.encode("utf-8"))


def create_access_token(user_id: int, tenant_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "tenant_id": tenant_id, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    return user


async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Ação restrita a administradores")
    return current_user


# ---------- Schemas ----------

class UserBase(BaseModel):
    id: int
    username: str
    tenant_id: int
    is_admin: bool
    nome: str | None = None
    sobrenome: str | None = None
    idade: int | None = None
    tipo_sanguineo: str | None = None
    telefone: str | None = None
    contato_emergencia_nome: str | None = None
    contato_emergencia_telefone: str | None = None

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    # Sem tenant_join_code: quem cadastra agora é um admin autenticado,
    # e o tenant já é conhecido pelo token dele.
    username: str
    nome: str | None = None
    sobrenome: str | None = None
    idade: int | None = None
    tipo_sanguineo: str | None = None
    telefone: str | None = None
    contato_emergencia_nome: str | None = None
    contato_emergencia_telefone: str | None = None


class UserProfileUpdate(BaseModel):
    # Usado pelo próprio usuário para editar seu perfil — tudo opcional,
    # só os campos enviados são alterados (exclude_unset na rota).
    nome: str | None = None
    sobrenome: str | None = None
    idade: int | None = None
    tipo_sanguineo: str | None = None
    telefone: str | None = None
    contato_emergencia_nome: str | None = None
    contato_emergencia_telefone: str | None = None


class TenantBase(BaseModel):
    id: int
    full_name: str
    slug: str
    join_code: str
    max_accounts: int

    model_config = ConfigDict(from_attributes=True)


class TenantCreate(BaseModel):
    full_name: str
    slug: str
    max_accounts: int = 5


class TenantExists(BaseModel):
    exists: bool


class UserCreatedResponse(UserBase):
    access_code: str  # devolvido em texto puro só nesta resposta, uma única vez


class LoginRequest(BaseModel):
    tenant_join_code: str
    access_code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AdminBootstrapCreate(BaseModel):
    username: str
    tenant_join_code: str


class LocationUpdate(BaseModel):
    latitude: float
    longitude: float


class PersonLocation(BaseModel):
    id: int
    username: str
    latitude: float
    longitude: float
    last_seen_at: datetime
    sos_ativo: bool

    model_config = ConfigDict(from_attributes=True)


class RoutePoint(BaseModel):
    latitude: float
    longitude: float


class RouteUpdate(BaseModel):
    points: list[RoutePoint]


class RouteResponse(BaseModel):
    points: list[RoutePoint]

    model_config = ConfigDict(from_attributes=True)


# ---------- Rotas: Tenant ----------

@app.post("/tenant", response_model=TenantBase)
async def create_tenant(
    tenant: TenantCreate,
    db: AsyncSession = Depends(get_db),
    x_setup_key: str = Header(...),
):
    """Criar um grupo/tenant novo é uma ação administrativa da sua infra —
    protegida pela mesma chave de setup do bootstrap de admin, não por login
    de usuário (ainda não existe nenhum usuário nesse tenant nesse momento)."""
    if not ADMIN_SETUP_KEY or not secrets.compare_digest(x_setup_key, ADMIN_SETUP_KEY):
        raise HTTPException(status_code=403, detail="Chave de setup inválida")

    db_tenant = Tenant(
        full_name=tenant.full_name,
        slug=tenant.slug,
        join_code=generate_join_code(),
        max_accounts=tenant.max_accounts,
    )
    db.add(db_tenant)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Já existe um tenant com esse slug")
    await db.refresh(db_tenant)
    return db_tenant


@app.get("/tenant/{join_code}/exists", response_model=TenantExists)
async def tenant_exists(join_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tenant).where(Tenant.join_code == join_code.upper()))
    tenant = result.scalar_one_or_none()
    return {"exists": tenant is not None}


# ---------- Rotas: User ----------

@app.get("/users", response_model=list[UserBase])
async def get_users(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Lista os usuários do MESMO tenant do admin logado — nunca de outros grupos."""
    results = await db.execute(select(User).where(User.tenant_id == current_admin.tenant_id))
    users = results.scalars().all()
    return users


@app.post("/user", response_model=UserCreatedResponse)
async def create_user(
    dados: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Cadastro de peregrino — agora é uma ação exclusiva do admin do grupo.
    Não existe mais autocadastro público: o tenant já é conhecido pelo
    token do admin, não é mais informado no corpo da requisição."""
    result = await db.execute(select(Tenant).where(Tenant.id == current_admin.tenant_id))
    tenant = result.scalar_one()

    count_result = await db.execute(
        select(func.count()).select_from(User).where(User.tenant_id == tenant.id)
    )
    current_accounts = count_result.scalar_one()
    if current_accounts >= tenant.max_accounts:
        raise HTTPException(
            status_code=403,
            detail="Limite de contas/licenças atingido para este grupo",
        )

    access_code = generate_access_code()
    db_user = User(
        username=dados.username,
        tenant_id=tenant.id,
        access_code_hash=hash_access_code(access_code),
        nome=dados.nome,
        sobrenome=dados.sobrenome,
        idade=dados.idade,
        tipo_sanguineo=dados.tipo_sanguineo,
        telefone=dados.telefone,
        contato_emergencia_nome=dados.contato_emergencia_nome,
        contato_emergencia_telefone=dados.contato_emergencia_telefone,
    )
    db.add(db_user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username já está em uso")
    await db.refresh(db_user)

    return UserCreatedResponse(
        **UserBase.model_validate(db_user).model_dump(),
        access_code=access_code,
    )


@app.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")  # limita tentativas por IP, protege contra força bruta no código
async def login(request: Request, credentials: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Tenant).where(Tenant.join_code == credentials.tenant_join_code.upper())
    )
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=401, detail="Grupo ou código inválido")

    result = await db.execute(
        select(User).where(User.tenant_id == tenant.id)
    )
    users = result.scalars().all()

    matched_user = next(
        (u for u in users if verify_access_code(credentials.access_code, u.access_code_hash)),
        None,
    )
    if matched_user is None:
        raise HTTPException(status_code=401, detail="Grupo ou código inválido")

    token = create_access_token(user_id=matched_user.id, tenant_id=tenant.id)
    return TokenResponse(access_token=token)


@app.get("/me", response_model=UserBase)
async def read_current_user(current_user: User = Depends(get_current_user)):
    """Exemplo de rota protegida — use Depends(get_current_user) em qualquer
    rota que precise saber quem é o peregrino logado (ex: enviar localização)."""
    return current_user


@app.patch("/me", response_model=UserBase)
async def update_my_profile(
    payload: UserProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cada usuário só edita o PRÓPRIO perfil — nunca recebe um user_id no
    path, current_user já garante isso."""
    dados = payload.model_dump(exclude_unset=True)
    for campo, valor in dados.items():
        setattr(current_user, campo, valor)
    await db.commit()
    await db.refresh(current_user)
    return current_user


# ---------- Rotas: Localização ----------

@app.post("/location")
async def update_location(
    payload: LocationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.last_latitude = payload.latitude
    current_user.last_longitude = payload.longitude
    # A coluna é TIMESTAMP WITHOUT TIME ZONE — removemos o tzinfo aqui,
    # já que o valor já está em UTC (só o Postgres não aceita o marcador).
    current_user.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    return {"ok": True}


@app.get("/pessoas", response_model=list[PersonLocation])
async def get_pessoas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(User).where(
            User.tenant_id == current_user.tenant_id,
            User.last_latitude.is_not(None),
            User.last_longitude.is_not(None),
        )
    )
    users = result.scalars().all()
    return [
        PersonLocation(
            id=u.id,
            username=u.username,
            latitude=u.last_latitude,
            longitude=u.last_longitude,
            last_seen_at=u.last_seen_at,
            sos_ativo=u.sos_ativo,
        )
        for u in users
    ]


# ---------- Rotas: SOS ----------

@app.post("/sos")
async def acionar_sos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """O próprio usuário aciona — a confirmação ("tem certeza?") é feita no
    app antes de chamar essa rota, aqui já é o acionamento de verdade."""
    current_user.sos_ativo = True
    current_user.sos_acionado_em = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    return {"ok": True}


@app.post("/sos/{user_id}/resolver")
async def resolver_sos(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Admin marca o alerta como atendido/resolvido."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if target.tenant_id != current_admin.tenant_id:
        raise HTTPException(status_code=403, detail="Usuário pertence a outro grupo")

    target.sos_ativo = False
    await db.commit()
    return {"ok": True}


# ---------- Rotas: Rota fixa do grupo ----------

@app.get("/tenant/route", response_model=RouteResponse)
async def get_route(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = result.scalar_one()
    return RouteResponse(points=tenant.route_points or [])


@app.put("/tenant/route", response_model=RouteResponse)
async def update_route(
    payload: RouteUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    result = await db.execute(select(Tenant).where(Tenant.id == current_admin.tenant_id))
    tenant = result.scalar_one()
    tenant.route_points = [p.model_dump() for p in payload.points]
    await db.commit()
    return RouteResponse(points=payload.points)


# ---------- Rotas: Admin ----------

@app.post("/admin/bootstrap", response_model=UserCreatedResponse)
async def bootstrap_admin(
    dados: AdminBootstrapCreate,
    db: AsyncSession = Depends(get_db),
    x_setup_key: str = Header(...),
):
    """Cria o primeiro admin de um tenant. Só funciona com a chave de setup
    do servidor (variável de ambiente ADMIN_SETUP_KEY) — nunca exponha essa
    chave no app, ela é de uso único/manual por quem administra a infra."""
    if not ADMIN_SETUP_KEY or not secrets.compare_digest(x_setup_key, ADMIN_SETUP_KEY):
        raise HTTPException(status_code=403, detail="Chave de setup inválida")

    result = await db.execute(
        select(Tenant).where(Tenant.join_code == dados.tenant_join_code.upper())
    )
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Grupo não encontrado")

    access_code = generate_access_code()
    db_user = User(
        username=dados.username,
        tenant_id=tenant.id,
        access_code_hash=hash_access_code(access_code),
        is_admin=True,
    )
    db.add(db_user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username já está em uso")
    await db.refresh(db_user)

    return UserCreatedResponse(
        **UserBase.model_validate(db_user).model_dump(),
        access_code=access_code,
    )


@app.post("/user/{user_id}/promote", response_model=UserBase)
async def promote_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if target.tenant_id != current_admin.tenant_id:
        raise HTTPException(status_code=403, detail="Usuário pertence a outro grupo")

    target.is_admin = True
    await db.commit()
    await db.refresh(target)
    return target


@app.post("/user/{user_id}/reset-code", response_model=UserCreatedResponse)
async def reset_user_code(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if target.tenant_id != current_admin.tenant_id:
        raise HTTPException(status_code=403, detail="Usuário pertence a outro grupo")

    novo_codigo = generate_access_code()
    target.access_code_hash = hash_access_code(novo_codigo)
    await db.commit()
    await db.refresh(target)

    return UserCreatedResponse(
        **UserBase.model_validate(target).model_dump(),
        access_code=novo_codigo,
    )