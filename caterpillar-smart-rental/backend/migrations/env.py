"""Use the startup connection so DDL and revision updates share its transaction."""
from alembic import context
from sqlalchemy import create_engine, pool


def run(connection):
    context.configure(connection=connection, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
elif context.is_offline_mode():
    context.configure(url=context.config.get_main_option("sqlalchemy.url"), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(context.config.get_main_option("sqlalchemy.url"), poolclass=pool.NullPool)
    with engine.begin() as connection:
        run(connection)
