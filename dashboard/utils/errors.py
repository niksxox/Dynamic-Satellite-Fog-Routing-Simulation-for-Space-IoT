def storage_error(exc):
    """Describe a storage failure without rendering connection strings or credentials."""
    return (f"{type(exc).__name__}. Check DATABASE_URL, PostgreSQL availability, "
            "network access, and user permissions. Connection details are hidden.")
