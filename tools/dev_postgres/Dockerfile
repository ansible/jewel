FROM mirror.gcr.io/library/postgres:15

ENV POSTGRES_DB=gw_db
ENV POSTGRES_USER=gw
ENV POSTGRES_PASSWORD=password

EXPOSE 5432

CMD ["-p", "5432"]

HEALTHCHECK --interval=10s --timeout=5s --retries=5 CMD ["pg_isready", "-U", "gw", "-d", "gw_db"]
