"""Initialize missing PostgreSQL tables without deleting existing records."""
from src.database.engine import create_database
from src.database.schema import initialize_schema


def main():
    database = create_database()
    try:
        initialize_schema(database)
        print("PostgreSQL schema initialized (existing records retained).")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
