from sqlalchemy import create_engine

def get_engine(connection_string: str = "sqlite:///:memory:"):
    return create_engine(connection_string)
