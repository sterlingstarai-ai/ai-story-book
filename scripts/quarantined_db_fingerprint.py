"""Compute a private content fingerprint for one isolated local PostgreSQL."""
import hashlib
import json
from contextlib import closing

import psycopg2
from psycopg2 import sql


def fingerprint():
    """Stream row hashes under one read-only snapshot; return no user content."""
    digest = hashlib.sha256()
    with closing(psycopg2.connect(host='127.0.0.1', port=54321, dbname='restored',
                                  user='sandbox', connect_timeout=5)) as connection:
        cursor = connection.cursor()
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        cursor.execute("""SELECT c.relname FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY c.relname""")
        tables = cursor.fetchall()
        if not tables:
            raise RuntimeError('Restored database contains no application tables')
        cursor.execute("""SELECT c.relname, a.attname,
                pg_catalog.format_type(a.atttypid,a.atttypmod), a.attnotnull
            FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p') AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY c.relname,a.attnum""")
        columns = cursor.fetchall()
        cursor.execute("""SELECT c.relname, con.conname, pg_catalog.pg_get_constraintdef(con.oid)
            FROM pg_catalog.pg_constraint con JOIN pg_catalog.pg_class c ON c.oid=con.conrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' ORDER BY c.relname,con.conname""")
        constraints = cursor.fetchall()
        digest.update(json.dumps([columns, constraints], separators=(',', ':'), ensure_ascii=True).encode() + b'\0')
        for index, (table,) in enumerate(tables):
            if not isinstance(table, str) or not table:
                raise RuntimeError('Restored table inventory is invalid')
            digest.update(table.encode('utf-8') + b'\0')
            statement = sql.SQL("SELECT encode(sha256(convert_to(to_jsonb(t)::text, 'UTF8')),'hex') AS row_hash "
                                "FROM {}.{} AS t ORDER BY row_hash").format(sql.Identifier('public'), sql.Identifier(table))
            count = 0
            with connection.cursor(name='asb_restore_fingerprint_' + str(index)) as cursor:
                cursor.execute(statement)
                for (row_hash,) in cursor:
                    if not isinstance(row_hash, str) or len(row_hash) != 64:
                        raise RuntimeError('Restored row fingerprint is invalid')
                    digest.update(row_hash.encode('ascii') + b'\n')
                    count += 1
            digest.update(str(count).encode('ascii') + b'\0')
    return digest.hexdigest()
