FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY web-scraper/requirements.txt /tmp/scraper-req.txt
COPY to-dojo/requirements.txt /tmp/dojo-req.txt

RUN grep -v '^playwright' /tmp/scraper-req.txt > /tmp/scraper-nopw.txt \
    && pip install --no-cache-dir -r /tmp/scraper-nopw.txt -r /tmp/dojo-req.txt \
    && rm -rf /tmp/scraper-req.txt /tmp/scraper-nopw.txt /tmp/dojo-req.txt

COPY --chown=appuser:appuser . /app

USER appuser

ENTRYPOINT ["python"]
CMD ["web-scraper/scraper.py", "--help"]
