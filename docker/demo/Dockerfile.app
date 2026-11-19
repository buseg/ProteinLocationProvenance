# Streamlit demo (app/v2.py). Talks to the fuseki service; reads the evaluation files under reports/.
FROM python:3.11-slim

WORKDIR /locx
COPY docker/demo/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && useradd --system --create-home locx

COPY config.yaml ./
COPY .streamlit ./.streamlit
COPY locx ./locx
COPY queries ./queries
COPY app ./app
COPY reports ./reports
COPY data/rdf/loaded.json ./data/rdf/loaded.json

USER locx
ENV LOCX_FUSEKI_BASE=http://fuseki:3030 PYTHONUNBUFFERED=1
EXPOSE 8501
CMD ["streamlit", "run", "app/v2.py", "--server.address", "0.0.0.0", "--server.port", "8501", \
     "--server.headless", "true", "--browser.gatherUsageStats", "false"]
