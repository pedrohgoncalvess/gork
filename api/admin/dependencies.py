from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError

from database import PgConnection


async def get_db():
    async with PgConnection() as db:
        try:
            yield db
        except IntegrityError:
            await db.rollback()
            raise HTTPException(409, "Já existe um registro com esse identificador.") from None
        except OperationalError:
            await db.rollback()
            raise HTTPException(503, "O banco de dados está indisponível. Tente novamente.") from None
