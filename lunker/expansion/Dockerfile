### warcio v1.7.5 ###

FROM public.ecr.aws/docker/library/python:latest

WORKDIR /app

COPY expansion.py requirements.txt .

RUN pip install -r requirements.txt --no-cache-dir --upgrade

ENTRYPOINT [ "python", "/app/expansion.py" ]
