"""Registration, login, and current-user endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from app.schemas.auth import Token
from app.schemas.user import UserCreate, UserLogin, UserRead

router = APIRouter()


def _issue_token(user: User) -> Token:
    token = create_access_token(subject=user.id, role=user.role.value)
    return Token(
        access_token=token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserRead.model_validate(user),
    )


@router.post(
    "/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> Token:
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )

    # First account bootstraps the instance as admin; everyone after is an
    # analyst until an admin promotes them.
    is_first_user = db.scalar(select(User).limit(1)) is None

    user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole.ADMIN if is_first_user else UserRole.ANALYST,
    )
    db.add(user)
    db.flush()
    db.add(AuditLog(user_id=user.id, action="user.register", payload={}))
    db.commit()
    db.refresh(user)

    return _issue_token(user)


@router.post("/login", response_model=Token, summary="Authenticate, return JWT")
def login(payload: UserLogin, db: Session = Depends(get_db)) -> Token:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))

    # Same response for unknown email and wrong password, so the endpoint
    # cannot be used to enumerate accounts.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )

    db.add(AuditLog(user_id=user.id, action="user.login", payload={}))
    db.commit()

    return _issue_token(user)


@router.get("/me", response_model=UserRead, summary="Current user")
def me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(user)
