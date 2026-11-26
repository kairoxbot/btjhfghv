FROM python:3.11-slim
WORKDIR /app
ENV PIP_ROOT_USER_ACTION=ignore
RUN pip install --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vnum_monitor.py .
EXPOSE 8080
CMD ["python", "vnum_monitor.py"]
