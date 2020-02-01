import json
from contextlib import contextmanager

from sqlalchemy import Column, Text, String, Integer, create_engine, Boolean
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from jarbas_hive_mind.settings import CLIENTS_DB

from sqlalchemy.ext.declarative import declarative_base

__author__ = "JarbasAI"


Base = declarative_base()


def model_to_dict(obj):
    serialized_data = {c.key: getattr(obj, c.key) for c in obj.__table__.columns}
    return serialized_data


def props(cls):
    return [i for i in cls.__dict__.keys() if i[:1] != '_']


@contextmanager
def session_scope(db):
    """Provide a transactional scope around a series of operations."""
    Session = sessionmaker(bind=db)
    session = Session()
    try:
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True)
    description = Column(Text)
    api_key = Column(String)
    name = Column(String)
    mail = Column(String)
    last_seen = Column(Integer, default=0)
    is_admin = Column(Boolean, default=False)
    blacklist = Column(Text)  # json string


class ClientDatabase(object):
    def __init__(self, path=CLIENTS_DB, debug=False):
        self.db = create_engine(path)
        self.db.echo = debug

        Base.metadata.create_all(self.db)

    def update_timestamp(self, key, timestamp):
        with session_scope(self.db) as session:
            user = self.get_client_by_api_key(key)
            if not user:
                return False
            user.last_seen = timestamp
            return True

    def delete_client(self, key):
        with session_scope(self.db) as session:
            user = self.get_client_by_api_key(key)
            if user:
                session.delete(user)
                return True
            return False

    def change_api(self, old_key, new_key):
        with session_scope(self.db) as session:
            user = self.get_client_by_api_key(old_key)
            if not user:
                return False
            user.api_key = new_key
        return True

    def change_name(self, new_name, key):
        with session_scope(self.db) as session:
            user = self.get_client_by_api_key(key)
            if not user:
                return False
            user.name = new_name
        return True

    def change_blacklist(self, blacklist, key):
        if isinstance(blacklist, dict):
            blacklist = json.dumps(blacklist)
        with session_scope(self.db) as session:
            user = self.get_client_by_api_key(key)
            if not user:
                return False
            user.blacklist = blacklist
        return True

    def get_blacklist_by_api_key(self, api_key):
        with session_scope(self.db) as session:
            user = session.query(Client).filter_by(api_key=api_key).first()
            return json.loads(user.blacklist)

    def get_client_by_api_key(self, api_key):
        with session_scope(self.db) as session:
            return session.query(Client).filter_by(api_key=api_key).first()

    def get_client_by_name(self, name):
        with session_scope(self.db) as session:
            return session.query(Client).filter_by(name=name).all()

    def add_client(self, name=None, mail=None, key="", admin=False,
                   blacklist="{}"):
        if isinstance(blacklist, dict):
            blacklist = json.dumps(blacklist)

        with session_scope(self.db) as session:
            user = self.get_client_by_api_key(key)
            if user:
                user.name = name
                user.mail = mail
                user.blacklist = blacklist
                user.is_admin = admin
            else:
                user = Client(api_key=key, name=name, mail=mail,
                              blacklist=blacklist, id=self.total_clients() + 1,
                              is_admin=admin)
                session.add(user)

    def total_clients(self):
        with session_scope(self.db) as session:
            return session.query(Client).count()

    def commit(self, handler):
        Session = sessionmaker(bind=self.db)
        session = Session()
        try:
            handler(session)
            session.commit()
        except IntegrityError:
            session.rollback()
            raise
        finally:
            session.close()

