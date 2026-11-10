# Official DP-Bench scorer (upstage/dp-bench evaluate.py + src/), isolated in a container.
# The scorer code is mounted at /dp (data/dpbench from the HF dataset repo); only its pinned deps are baked in.
FROM python:3.12-slim
RUN pip install --no-cache-dir rapidfuzz==3.6.1 distance==0.1.3 apted==1.0.3 lxml==5.3.0 numpy scipy shapely
WORKDIR /dp
ENTRYPOINT ["python", "evaluate.py"]
