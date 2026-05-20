FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /server

COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

COPY server.py schemas.py ./

CMD ["python", "server.py"]
