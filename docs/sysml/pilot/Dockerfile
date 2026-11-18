# SysML v2 Pilot Implementation (OMG reference) as a headless Jupyter server.
# Kernel "sysml" renders %viz diagrams via PlantUML + Graphviz.
# Versions follow SysML-v2-Release 2026-09.1 (install/jupyter/install.sh).
FROM condaforge/miniforge3:26.9.4-2

RUN conda install -y -c conda-forge \
        "jupyter-sysml-kernel=0.63.1" \
        "openjdk=21" \
        "graphviz=2.*" \
        jupyter_server \
    && conda clean -afy \
    && jupyter kernelspec list | grep -q sysml \
    && dot -V \
    && java -version

WORKDIR /models
EXPOSE 8888
CMD ["jupyter", "server", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root"]
