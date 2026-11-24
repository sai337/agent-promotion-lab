# package-advisor agent image. Stdlib only: no dependencies to vet.
FROM python:3.13-slim
RUN groupadd --gid 1500 agent && useradd --uid 1500 --gid agent --create-home agent \
    && install -d -o agent -g agent /sandbox /app
COPY advisor.py /app/advisor.py
WORKDIR /sandbox
USER agent
CMD ["sleep", "infinity"]
