from contextlib import contextmanager


@contextmanager
def session_scope(factory):
    """Commit once on success and roll back on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
