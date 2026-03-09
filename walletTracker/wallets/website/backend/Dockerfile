# python 3.13 slim keeps the image small (~150MB vs ~900MB for the full image)
# slim still has everything we need — gcc, pip, etc.
FROM python:3.13-slim

WORKDIR /app

# copy requirements first so docker caches the pip install layer.
# code changes won't re-trigger a full pip install unless deps change
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# now copy the rest of the app
COPY . .

EXPOSE 8000

# run with 0.0.0.0 so the container is reachable from outside.
# no --reload in production, that's a dev-only thing
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

