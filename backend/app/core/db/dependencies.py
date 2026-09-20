from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session


def get_db_session(request: Request) -> Generator[Session, None, None]:
    database = request.app.state.database
    session = database.session_factory()
    try:
        yield session
    finally:
        session.close()
