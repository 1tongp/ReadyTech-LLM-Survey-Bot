from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

engine = create_engine("sqlite:///./survey.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ensure ON DELETE CASCADE is respected at DB level
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
    
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
