from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import DATABASE_URL

class Base(DeclarativeBase):
    pass

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={'connect_timeout': 3,'options':'-c statement_timeout=10000 -c lock_timeout=3000'})
Session = sessionmaker(engine, expire_on_commit=False)

def session():
    with Session() as db:
        yield db
