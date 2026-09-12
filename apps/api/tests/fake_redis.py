"""Deterministic Redis boundary for HTTP tests; no network or policy bypass."""


class FakeRedis:
    def __init__(self):
        self.counters = {}
        self.sorted_sets = {}
        self.ttls = {}

    async def eval(self, script, numkeys, key, now, window, limit, member):
        # Boundary fake for admission HTTP tests; real Lua behavior is exercised
        # separately against Redis, including same-timestamp concurrency.
        import math
        members = self.sorted_sets.setdefault(key, {})
        for old in [item for item, score in members.items() if score <= now - window]:
            del members[old]
        if len(members) >= limit:
            return [0, 0, max(1, math.ceil(min(members.values()) + window - now))]
        members[member] = now
        self.ttls[key] = math.ceil(window) + 1
        return [1, limit - len(members), 0]

    async def ping(self):
        return True

    async def get(self, key):
        value = self.counters.get(key)
        return str(value).encode() if value is not None else None

    async def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key, ttl):
        self.ttls[key] = ttl
        return True

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []

    def zremrangebyscore(self, key, lower, upper):
        self.commands.append(("remove", key, lower, upper))
        return self

    def zadd(self, key, values):
        self.commands.append(("add", key, values))
        return self

    def zcard(self, key):
        self.commands.append(("count", key))
        return self

    def expire(self, key, ttl):
        self.commands.append(("expire", key, ttl))
        return self

    async def execute(self):
        results = []
        for command, key, *args in self.commands:
            members = self.redis.sorted_sets.setdefault(key, {})
            if command == "remove":
                removed = [
                    member for member, score in members.items() if args[0] <= score <= args[1]
                ]
                for member in removed:
                    del members[member]
                results.append(len(removed))
            elif command == "add":
                added = len(set(args[0]) - set(members))
                members.update(args[0])
                results.append(added)
            elif command == "count":
                results.append(len(members))
            elif command == "expire":
                results.append(await self.redis.expire(key, args[0]))
        return results
