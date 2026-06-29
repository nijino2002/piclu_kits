from database import Base, get_engine
import models  # noqa: F401 - registers all model tables


if __name__ == "__main__":
    Base.metadata.create_all(get_engine())
    print("MySQL tables created or already present.")
