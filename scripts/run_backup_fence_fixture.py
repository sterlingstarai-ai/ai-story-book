"""Test the PostgreSQL backup write fence on an owned disposable database."""

import asyncio
import os
import uuid
from urllib.parse import urlsplit

import boto3
import httpx
import psycopg
from botocore.config import Config
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from psycopg import sql

from run_restore_replay_fixture import require_local_fixture
from postgres_backup_fence import PostgresBackupFence


def main():
    require_local_fixture()
    url = urlsplit(os.environ['DATABASE_URL'])
    environment = {'PGHOST': url.hostname, 'PGPORT': str(url.port), 'PGUSER': url.username,
                   'PGPASSWORD': url.password, 'PGDATABASE': url.path.lstrip('/'), 'PGSSLMODE': 'disable'}
    params = {'host': url.hostname, 'port': url.port, 'user': url.username,
              'password': url.password, 'dbname': url.path.lstrip('/'), 'sslmode': 'disable'}
    s3 = boto3.client('s3', endpoint_url=os.environ['S3_ENDPOINT'], aws_access_key_id='runtime_test',
                      aws_secret_access_key='disposable-runtime-password', region_name='us-east-1',
                      config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}))
    bucket = 'asb-fence-' + uuid.uuid4().hex
    s3.create_bucket(Bucket=bucket)
    app = FastAPI()

    @app.get('/fixture')
    async def read_fixture():
        with psycopg.connect(**params, autocommit=True) as reader:
            return {'count': reader.execute('SELECT count(*) FROM public.asb_fence_fixture').fetchone()[0]}

    @app.delete('/fixture')
    async def reject_mutation():
        # This synthetic admission policy is NOT installed in the real app.
        return JSONResponse({'status': 'maintenance'}, status_code=503)

    async def exercise_synthetic_http():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            read = await client.get('/fixture')
            delete = await client.delete('/fixture')
            if read.status_code != 200 or read.json() != {'count': 1} or delete.status_code != 503:
                raise RuntimeError('Synthetic read-only HTTP behavior was unexpected')
    table_created = False
    try:
        with psycopg.connect(**params, autocommit=True) as setup:
            setup.execute('CREATE TABLE public.asb_fence_fixture (value integer NOT NULL)')
            table_created = True
            setup.execute('INSERT INTO public.asb_fence_fixture VALUES (1)')
        with PostgresBackupFence(environment) as fence:
            asyncio.run(exercise_synthetic_http())
            with psycopg.connect(**params, autocommit=True) as other:
                other.execute("SET lock_timeout = '300ms'")
                for statement in ('INSERT INTO public.asb_fence_fixture VALUES (2)',
                                  'DELETE FROM public.asb_fence_fixture'):
                    try:
                        other.execute(statement)
                    except psycopg.errors.LockNotAvailable:
                        pass
                    else:
                        raise RuntimeError('Synthetic writer was not blocked by the backup fence')
            # Prove the production blocker, rather than assuming DB locks
            # fence S3: another actor can still create and delete an object.
            s3.put_object(Bucket=bucket, Key='fixture', Body=b'synthetic')
            body = s3.get_object(Bucket=bucket, Key='fixture')['Body']
            try:
                if body.read() != b'synthetic':
                    raise RuntimeError('Synthetic storage mutation did not succeed')
            finally:
                body.close()
            s3.delete_object(Bucket=bucket, Key='fixture')
            with psycopg.connect(**params, autocommit=True) as reader:
                reader.execute('BEGIN ISOLATION LEVEL REPEATABLE READ')
                reader.execute(sql.SQL('SET TRANSACTION SNAPSHOT {}').format(sql.Literal(fence.snapshot_id)))
                if reader.execute('SELECT count(*) FROM public.asb_fence_fixture').fetchone()[0] != 1:
                    raise RuntimeError('Synthetic exported snapshot did not match')
                reader.execute('ROLLBACK')
            fence.verify()
        with psycopg.connect(**params, autocommit=True) as other:
            other.execute('INSERT INTO public.asb_fence_fixture VALUES (2)')
            if other.execute('SELECT count(*) FROM public.asb_fence_fixture').fetchone()[0] != 2:
                raise RuntimeError('Synthetic writer did not resume after backup')
        print('Synthetic HTTP read succeeded, delete rejected; DB insert/delete blocked; independent S3 mutation remained possible')
    finally:
        try:
            if table_created:
                with psycopg.connect(**params, autocommit=True) as cleanup:
                    cleanup.execute('DROP TABLE public.asb_fence_fixture')
        finally:
            try:
                s3.delete_object(Bucket=bucket, Key='fixture')
                s3.delete_bucket(Bucket=bucket)
            finally:
                s3.close()


if __name__ == '__main__':
    main()
