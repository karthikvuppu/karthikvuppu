FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy
WORKDIR /app
RUN pip install --no-cache-dir "playwright==1.49.0" fastapi "uvicorn[standard]"
COPY app.py .
ENV BROWSER_PROFILE_DIR=/data/profile
EXPOSE 8100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
