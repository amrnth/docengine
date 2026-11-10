# Official ParseBench scorer (run-llama/ParseBench), isolated in a container.
FROM python:3.12-slim
RUN pip install --no-cache-dir parse-bench aiohttp pdf2image llama-cloud
WORKDIR /work
ENTRYPOINT ["parse-bench"]
